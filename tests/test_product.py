"""v0.3 product features: template ids, typography, transitions, mastering, QA, sidecars."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.create_editorial_demo import create_demo, write_tone
from videogenome.__main__ import EXIT_GATE_FAILED, main
from videogenome.blueprint import validate_blueprint
from videogenome.catalog import discover
from videogenome.compiler import ROOT, ProductionError, compile_job
from videogenome.deliverables import subtitles
from videogenome.layout import balanced_wrap, fit_copy, resolve_title_card
from videogenome.qa import evaluate_gates
from videogenome.render import render

CARDS = ROOT / "templates/educational/title-card-sequence/blueprint.json"
VERTICAL = ROOT / "templates/social/vertical-tips/blueprint.json"
HYBRID = ROOT / "templates/reference/hybrid-assembly-smoke/blueprint.json"
CARDS_JOB = ROOT / "examples/three-card-explainer/job.json"
VERTICAL_JOB = ROOT / "examples/vertical-tips/job.json"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def rgb_frame(movie: Path, frame: int, width: int, height: int) -> bytes:
    data = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(movie),
         "-vf", f"select='eq(n,{frame})'", "-fps_mode", "passthrough", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    assert len(data) == width * height * 3
    return data


class TemplateResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_job_can_name_a_template_by_catalog_id_anywhere(self) -> None:
        plan = compile_job(write(self.root / "job.json", load(CARDS_JOB)))
        self.assertEqual(plan["template_id"], "educational.title-card-sequence")
        self.assertEqual(plan["ir_version"], "0.5.0")

    def test_unknown_template_id_is_reported(self) -> None:
        job = load(CARDS_JOB)
        job["template"] = "educational.does-not-exist"
        with self.assertRaisesRegex(ProductionError, "Unknown template"):
            compile_job(write(self.root / "job.json", job))

    def test_external_template_directory_must_be_trusted_by_operator(self) -> None:
        blueprint = load(CARDS)
        blueprint["id"] = "studio.house-cards"
        write(self.root / "studio" / "cards" / "blueprint.json", blueprint)
        job = load(CARDS_JOB)
        job["template"] = "studio.house-cards"
        manifest = write(self.root / "job.json", job)
        with self.assertRaisesRegex(ProductionError, "Unknown template"):
            compile_job(manifest)
        plan = compile_job(manifest, template_dirs=[self.root / "studio"])
        self.assertEqual(plan["template_id"], "studio.house-cards")
        ids = {entry["id"] for entry in discover(template_dirs=[self.root / "studio"])}
        self.assertIn("studio.house-cards", ids)
        # A path into an untrusted directory is refused even if it exists.
        job["template"] = str(self.root / "studio" / "cards" / "blueprint.json")
        with self.assertRaisesRegex(ProductionError, "trusted"):
            compile_job(write(self.root / "job.json", job))

    def test_duplicate_template_ids_are_ambiguous(self) -> None:
        write(self.root / "copy" / "blueprint.json", load(CARDS))
        with self.assertRaisesRegex(ProductionError, "more than once"):
            compile_job(write(self.root / "job.json", load(CARDS_JOB)),
                        template_dirs=[self.root / "copy"])


class CopyFittingTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.job = load(VERTICAL_JOB)

    def compile(self) -> dict:
        return compile_job(write(self.root / "job.json", self.job))

    def test_balanced_wrap_avoids_orphans(self) -> None:
        self.assertEqual(balanced_wrap("Design once. Adapt the content.", 27),
                         ["Design once. Adapt", "the content."])
        self.assertEqual(balanced_wrap("Short", 20), ["Short"])

    def test_copy_wraps_within_locked_line_limit(self) -> None:
        segments = {s["shot_id"]: s for s in self.compile()["segments"]}
        tip = segments["tip_2_card"]
        self.assertLessEqual(len(tip["lines"]), 5)
        self.assertEqual(" ".join(tip["lines"]), self.job["inputs"]["tip_2"])
        self.assertEqual(segments["tip_1_card"]["kicker"], "01 / 03")
        self.assertEqual(segments["hook_card"]["kicker"], "")

    def test_overlong_copy_is_rejected_not_shrunk_illegibly(self) -> None:
        self.job["inputs"]["hook"] = "An extremely long opening promise " * 6
        with self.assertRaisesRegex(ProductionError, "hook_card.*does not fit"):
            self.compile()

    def test_control_characters_are_rejected(self) -> None:
        self.job["inputs"]["cta"] = "Save\x07 this"
        with self.assertRaisesRegex(ProductionError, "control characters"):
            self.compile()

    def test_legacy_cards_keep_their_look_but_wrap(self) -> None:
        blueprint = load(HYBRID)
        card = resolve_title_card(blueprint)
        self.assertEqual((card["font_family"], card["align"], card["entrance"]), ("Sans", "center", "none"))
        size, lines = fit_copy(card, "A deliberately long closing title", "", blueprint["output"])
        self.assertGreater(len(lines), 1)
        self.assertGreaterEqual(size, card["min_font_size"])


class BlueprintV03ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blueprint = load(VERTICAL)

    def errors(self) -> list[str]:
        return validate_blueprint(self.blueprint)

    def test_shipped_templates_validate(self) -> None:
        self.assertEqual(self.errors(), [])

    def test_new_features_require_schema_0_3(self) -> None:
        self.blueprint["schema_version"] = "0.2.0"
        errors = self.errors()
        for feature in ("style.title_card", "output.loudness", "timeline transitions",
                        "kicker_template", "check"):
            self.assertTrue(any(feature in e for e in errors), feature)

    def test_title_card_colours_must_come_from_palette(self) -> None:
        self.blueprint["style"]["title_card"]["accent_color"] = "#00FF00"
        self.assertTrue(any("not in the locked palette" in e for e in self.errors()))

    def test_transitions_must_reference_real_non_final_shots(self) -> None:
        transitions = self.blueprint["timeline"]["transitions"]
        transitions.append({"after_shot": "ghost", "kind": "dip", "duration_frames": 4})
        transitions.append({"after_shot": "cta_card", "kind": "dip", "duration_frames": 4})
        transitions.append(dict(transitions[0]))
        errors = self.errors()
        self.assertTrue(any("unknown shot 'ghost'" in e for e in errors))
        self.assertTrue(any("final shot" in e for e in errors))
        self.assertTrue(any("duplicate transition" in e for e in errors))

    def test_transitions_cannot_consume_a_whole_shot(self) -> None:
        self.blueprint["timeline"]["transitions"][0] = {
            "after_shot": "hook_card", "kind": "crossfade", "duration_frames": 90}
        self.assertTrue(any("tip_1_card" in e and "no clean frames" in e for e in self.errors()))

    def test_machine_checks_only_on_automated_gates(self) -> None:
        self.blueprint["quality_gates"][3]["check"] = {"metric": "black_seconds", "max": 1}
        self.blueprint["quality_gates"][0]["check"] = {"metric": "integrated_lufs"}
        errors = self.errors()
        self.assertTrue(any("only automated gates" in e for e in errors))
        self.assertTrue(any("needs min and/or max" in e for e in errors))

    def test_font_family_cannot_smuggle_filter_syntax(self) -> None:
        self.blueprint["style"]["title_card"]["font_family"] = "Inter:fontcolor=red"
        self.assertTrue(self.errors())


class GateAndSidecarUnitTests(unittest.TestCase):
    MEASURED = {"metrics": {"integrated_lufs": -14.2, "true_peak_dbtp": -1.4, "black_seconds": 0.0,
                            "longest_blank_seconds": 0.8},
                "not_applicable": {}, "sources": {"integrated_lufs": "FFmpegAnalyzer"}}

    def test_gates_pass_fail_or_stay_unevaluated(self) -> None:
        gates = [
            {"id": "loud", "mode": "automated", "description": "x" * 10, "status": "not_evaluated",
             "check": {"metric": "integrated_lufs", "min": -15, "max": -13}},
            {"id": "blank", "mode": "automated", "description": "x" * 10, "status": "not_evaluated",
             "check": {"metric": "longest_blank_seconds", "max": 0.5}},
            {"id": "taste", "mode": "automated", "description": "x" * 10, "status": "not_evaluated"},
            {"id": "human", "mode": "human", "description": "x" * 10, "status": "self_attested_approved"},
            {"id": "wer", "mode": "automated", "description": "x" * 10, "status": "not_evaluated",
             "check": {"metric": "word_error_rate", "max": 0.1}},
        ]
        evaluated = {g["id"]: g for g in evaluate_gates(gates, self.MEASURED)}
        self.assertEqual({k: g["status"] for k, g in evaluated.items()},
                         {"loud": "passed", "blank": "failed", "taste": "not_evaluated",
                          "human": "self_attested_approved", "wer": "not_evaluated"})
        self.assertEqual(evaluated["loud"]["evidence"]["source"], "FFmpegAnalyzer")
        self.assertIn("no configured analyzer", evaluated["wer"]["evidence"]["reason"])
        silent = {**self.MEASURED, "not_applicable": {"integrated_lufs": "programme audio is silent"}}
        self.assertEqual(evaluate_gates(gates[:1], silent)[0]["status"], "not_applicable")

    def test_subtitles_use_frame_exact_timestamps(self) -> None:
        plan = {"output": {"fps": 24}, "timeline": {"captions": {"cues": [
            {"id": "intro", "start_frame": 12, "end_frame": 72, "lines": ["Hello", "world"]},
            {"id": "late", "start_frame": 86400, "end_frame": 86424, "lines": ["One hour"]},
        ]}}}
        srt, vtt = subtitles(plan)
        self.assertIn("1\n00:00:00,500 --> 00:00:03,000\nHello\nworld\n", srt)
        self.assertIn("01:00:00,000 --> 01:00:01,000", srt)
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("intro\n00:00:00.500 --> 00:00:03.000", vtt)
        self.assertIsNone(subtitles({"output": {"fps": 24}}))


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class ProductRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_vertical_music_is_mastered_and_machine_gated(self) -> None:
        write_tone(self.root / "bed.wav", 330, 14)
        job = load(VERTICAL_JOB)
        job["inputs"]["music"] = "bed"
        job["assets"] = {"bed": {
            "kind": "audio", "path": "bed.wav",
            "origin": {"type": "rendered", "description": "Synthetic 330 Hz test tone"},
            "rights": {"cleared": True, "license": "MIT", "evidence": "Generated by the test suite"},
        }}
        movie = self.root / "vertical.mp4"
        receipt = render(compile_job(write(self.root / "job.json", job)), self.root, movie)
        self.assertEqual(receipt["frames_observed"], 405)
        self.assertEqual(receipt["loudness_normalization"]["status"], "applied")
        self.assertAlmostEqual(receipt["measurements"]["integrated_lufs"], -14, delta=1.0)
        status = {g["id"]: g["status"] for g in receipt["quality_gates"]}
        self.assertEqual(status["programme_loudness"], "passed")
        self.assertEqual(status["true_peak_headroom"], "passed")
        self.assertEqual(status["no_dead_picture"], "passed")
        self.assertEqual(status["claims_review"], "not_evaluated")
        self.assertIn("automated_gate_checks", receipt["verified"])
        for layout in receipt["title_layout"]:
            self.assertLessEqual(max(layout["line_widths_px"]), layout["available_width_px"])
        self.assertTrue(Path(receipt["deliverables"]["poster"]["path"]).stat().st_size > 1000)
        self.assertTrue(Path(receipt["deliverables"]["contact_sheet"]["path"]).is_file())
        self.assertNotIn("srt", receipt["deliverables"])

    def test_silent_vertical_reports_loudness_not_applicable(self) -> None:
        manifest = write(self.root / "job.json", load(VERTICAL_JOB))
        receipt = render(compile_job(manifest), self.root, self.root / "silent.mp4",
                         write_deliverables=False)
        status = {g["id"]: g["status"] for g in receipt["quality_gates"]}
        self.assertEqual(status["programme_loudness"], "not_applicable")
        self.assertEqual(receipt["loudness_normalization"]["status"], "skipped")
        self.assertEqual(receipt["deliverables"], {})

    def test_measured_glyphs_shrink_copy_the_estimate_underrated(self) -> None:
        job = load(CARDS_JOB)
        # Capitals run far wider than the mixed-case estimate.
        job["inputs"]["headline"] = "WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW WWWWWWWW"
        plan = compile_job(write(self.root / "job.json", job))
        receipt = render(plan, self.root, self.root / "wide.mp4", write_deliverables=False)
        layout = receipt["title_layout"][0]
        self.assertLess(layout["font_size"], layout["planned_font_size"])
        self.assertLessEqual(max(layout["line_widths_px"]), layout["available_width_px"])

    def test_crossfade_blends_shots_and_preserves_frame_count(self) -> None:
        blueprint = load(HYBRID)
        blueprint["schema_version"] = "0.3.0"
        blueprint["id"] = "test.hybrid-crossfade"
        blueprint["timeline"] = {"transitions": [
            {"after_shot": "live_clip", "kind": "crossfade", "duration_frames": 8},
            {"after_shot": "product_still", "kind": "dip", "duration_frames": 6},
        ], "fade_in_frames": 4}
        templates = self.root / "templates"
        write(templates / "hybrid" / "blueprint.json", blueprint)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x320:r=24:d=2",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
             "-t", "1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             str(self.root / "clip.mp4")], check=True)
        (self.root / "still.ppm").write_bytes(b"P6\n2 2\n255\n" + bytes([255, 0, 0] * 4))
        rights = {"cleared": True, "license": "owned", "evidence": "synthetic test fixture"}
        job = {
            "job_schema": "0.1.0", "id": "test.crossfade", "template": "test.hybrid-crossfade",
            "template_version": blueprint["version"],
            "inputs": {"title": "Fin", "camera_source": "video", "still_source": "image"},
            "assets": {
                "video": {"path": "clip.mp4", "kind": "video",
                          "origin": {"type": "rendered", "description": "CI test"}, "rights": rights},
                "image": {"path": "still.ppm", "kind": "image",
                          "origin": {"type": "owned", "description": "CI test"}, "rights": rights},
            },
            "shot_assets": {"live_clip": {"asset": "video", "fit": "cover"},
                            "product_still": {"asset": "image", "fit": "cover"}},
        }
        manifest = write(self.root / "job.json", job)
        plan = compile_job(manifest, template_dirs=[templates])
        self.assertEqual(plan["picture"]["transitions"][0]["cut_frame"], 24)
        movie = self.root / "xfade.mp4"
        receipt = render(plan, self.root, movie, write_deliverables=False)
        self.assertEqual(receipt["frames_observed"], 72)
        clip, blend, still = (rgb_frame(movie, n, 320, 320)[:3] for n in (16, 28, 40))
        self.assertGreater(clip[2], 180)
        self.assertLess(clip[0], 60)
        self.assertTrue(60 < blend[0] < 200 and 60 < blend[2] < 200, blend)
        self.assertGreater(still[0], 180)
        self.assertLess(still[2], 60)

        job["shot_assets"]["live_clip"]["in_seconds"] = 0.3
        manifest = write(self.root / "job.json", job)
        with self.assertRaisesRegex(ProductionError, "crossfade handle"):
            render(compile_job(manifest, template_dirs=[templates]), self.root,
                   self.root / "short.mp4")

    def test_captioned_render_writes_matching_subtitle_sidecars(self) -> None:
        manifest = create_demo(self.root / "editorial")
        movie = self.root / "editorial" / "out.mp4"
        receipt = render(compile_job(manifest), manifest.parent, movie)
        srt = Path(receipt["deliverables"]["srt"]["path"]).read_text(encoding="utf-8")
        self.assertIn("00:00:00,500 --> 00:00:03,000", srt)
        # Sidecars keep the same line breaks as the burned-in captions.
        self.assertIn("Start with a quiet music\nbed.\n", srt)
        self.assertTrue(Path(receipt["deliverables"]["vtt"]["path"]).is_file())

    def test_cli_exits_nonzero_when_an_automated_gate_fails(self) -> None:
        blueprint = load(CARDS)
        blueprint["id"] = "test.strict-cards"
        for gate in blueprint["quality_gates"]:
            if gate["id"] == "no_dead_picture":
                gate["check"]["max"] = 0  # Dips always produce a few blank frames.
        templates = self.root / "templates"
        write(templates / "strict" / "blueprint.json", blueprint)
        job = {**load(CARDS_JOB), "template": "test.strict-cards"}
        manifest = write(self.root / "job.json", job)
        output, receipt = self.root / "strict.mp4", self.root / "receipt.json"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["render", str(manifest), "-o", str(output), "--receipt", str(receipt),
                         "--templates", str(templates)])
        self.assertEqual(code, EXIT_GATE_FAILED)
        self.assertTrue(output.is_file())
        gates = {g["id"]: g for g in load(receipt)["quality_gates"]}
        self.assertEqual(gates["no_dead_picture"]["status"], "failed")
        self.assertGreater(gates["no_dead_picture"]["evidence"]["value"], 0)

    def test_doctor_reports_a_working_toolchain(self) -> None:
        from videogenome.doctor import diagnose
        rows = diagnose()
        self.assertFalse([row for row in rows if row[0] == "FAIL"], rows)


if __name__ == "__main__":
    unittest.main()
