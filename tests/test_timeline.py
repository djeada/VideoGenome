"""Contract checks and decoded-media evidence for the editorial timeline."""
from __future__ import annotations

import array
import copy
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.create_editorial_demo import create_demo, write_tone
from tools.validate import validate_blueprint
from videogenome.compiler import ROOT, ProductionError, compile_job, sha256_file
from videogenome.render import render

TEMPLATE = ROOT / "templates/educational/captioned-explainer/blueprint.json"


class TimelineValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blueprint = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    def test_timeline_requires_new_schema_version(self) -> None:
        self.assertEqual(validate_blueprint(self.blueprint), [])
        self.blueprint["schema_version"] = "0.1.0"
        self.assertTrue(validate_blueprint(self.blueprint))

    def test_rejects_invalid_audio_schedule(self) -> None:
        for patch, message in (
            ({"input_ref": "image"}, "audio input"),
            ({"input_ref": "missing"}, "audio input"),
            ({"start_frame": 180}, "beyond"),
            ({"fade_in_frames": 192}, "fades exceed"),
        ):
            with self.subTest(patch=patch):
                blueprint = copy.deepcopy(self.blueprint)
                blueprint["timeline"]["audio_tracks"][0].update(patch)
                self.assertTrue(any(message in e for e in validate_blueprint(blueprint)))

    def test_rejects_duplicate_tracks_and_cues(self) -> None:
        self.blueprint["timeline"]["audio_tracks"][1]["id"] = "music_bed"
        self.blueprint["timeline"]["captions"]["cues"][1]["id"] = "intro"
        errors = validate_blueprint(self.blueprint)
        self.assertTrue(any("duplicate audio track" in e for e in errors))
        self.assertTrue(any("duplicate caption cue" in e for e in errors))

    def test_rejects_caption_overlap_and_overrun(self) -> None:
        cues = self.blueprint["timeline"]["captions"]["cues"]
        cues[1]["start_frame"] = 60
        cues[2]["duration_frames"] = 100
        errors = validate_blueprint(self.blueprint)
        self.assertTrue(any("overlaps" in e for e in errors))
        self.assertTrue(any("beyond" in e for e in errors))

    def test_rejects_caption_style_outside_frame(self) -> None:
        for patch, message in (({"margin_x": 160}, "horizontal"),
                               ({"margin_bottom": 350}, "vertical")):
            with self.subTest(patch=patch):
                blueprint = copy.deepcopy(self.blueprint)
                blueprint["timeline"]["captions"]["style"].update(patch)
                self.assertTrue(any(message in e for e in validate_blueprint(blueprint)))

    def test_caption_flags_and_references_are_enforced(self) -> None:
        self.blueprint["output"]["captions"] = False
        self.blueprint["timeline"]["captions"]["cues"][0]["text_template"] = "{{music}}"
        errors = validate_blueprint(self.blueprint)
        self.assertTrue(any("output.captions" in e for e in errors))
        self.assertTrue(any("invalid text input" in e for e in errors))
        del self.blueprint["timeline"]["captions"]
        self.blueprint["output"]["captions"] = True
        self.assertTrue(any("requires timeline caption cues" in e for e in validate_blueprint(self.blueprint)))


class TimelineCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manifest = create_demo(self.root)
        self.job = json.loads(self.manifest.read_text(encoding="utf-8"))

    def compile(self) -> dict:
        self.manifest.write_text(json.dumps(self.job), encoding="utf-8")
        return compile_job(self.manifest)

    def test_compiles_audio_bindings_and_caption_cues(self) -> None:
        plan = self.compile()
        self.assertEqual(plan["ir_version"], "0.5.0")
        self.assertEqual(plan["total_frames"], 192)
        self.assertEqual(plan["timeline"]["audio_tracks"][1]["asset_id"], "narration")
        self.assertEqual(plan["timeline"]["audio_tracks"][1]["start_frame"], 48)
        self.assertEqual(plan["timeline"]["audio_tracks"][0]["in_frame"], 24)
        self.assertEqual(plan["timeline"]["captions"]["cues"][0]["end_frame"], 72)
        self.assertEqual(plan["assets"]["narration"]["sha256"], sha256_file(self.root / "narration.wav"))

    def test_audio_requires_inputs_compatible_assets_and_rights(self) -> None:
        original = copy.deepcopy(self.job)
        del self.job["inputs"]["narration"]
        with self.assertRaisesRegex(ProductionError, "Missing required input"):
            self.compile()
        self.job = copy.deepcopy(original)
        self.job["inputs"]["narration"] = "illustration"
        with self.assertRaisesRegex(ProductionError, "audio asset"):
            self.compile()
        self.job = copy.deepcopy(original)
        self.job["assets"]["narration"]["rights"]["cleared"] = False
        with self.assertRaisesRegex(ProductionError, "not rights-cleared"):
            self.compile()

    def test_caption_copy_must_fit_locked_reading_limits(self) -> None:
        for text, message in (
            ("   ", "nonempty"), ("x" * 29, "word too long"),
            ("word " * 14, "line limit"),
            ("One two three four five six seven eight nine.", "reading-speed"),
        ):
            with self.subTest(text=text):
                self.job["inputs"]["caption_close"] = text
                with self.assertRaisesRegex(ProductionError, message):
                    self.compile()

    def test_copy_wraps_without_changing_locked_timing(self) -> None:
        self.job["inputs"]["caption_intro"] = "A longer caption wraps over two lines."
        cue = self.compile()["timeline"]["captions"]["cues"][0]
        self.assertEqual(cue["lines"], ["A longer caption wraps over", "two lines."])
        self.assertEqual((cue["start_frame"], cue["end_frame"]), (12, 72))

    def test_job_cannot_override_timeline(self) -> None:
        self.job["timeline"] = {"source_audio": "mute"}
        with self.assertRaisesRegex(ProductionError, "Invalid production job"):
            self.compile()

    def test_two_briefs_share_the_same_locked_recipe(self) -> None:
        first = self.compile()
        second = compile_job(create_demo(self.root / "learning", brief="learning"))
        self.assertEqual(first["template_sha256"], second["template_sha256"])
        self.assertEqual(first["timeline"]["audio_tracks"], second["timeline"]["audio_tracks"])
        self.assertNotEqual(first["timeline"]["captions"]["cues"][0]["text"],
                            second["timeline"]["captions"]["cues"][0]["text"])


def decoded_audio(path: Path) -> array.array:
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
         "-ar", "48000", "-ac", "1", "-f", "f32le", "pipe:1"],
        capture_output=True, check=True
    ).stdout
    samples = array.array("f")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def tone_level(samples: array.array, frequency: float, at: float, seconds: float = 0.1) -> float:
    window = samples[round(at * 48000):round((at + seconds) * 48000)]
    real = sum(value * math.cos(2 * math.pi * frequency * i / 48000) for i, value in enumerate(window))
    imag = sum(value * math.sin(2 * math.pi * frequency * i / 48000) for i, value in enumerate(window))
    return 2 * math.hypot(real, imag) / len(window)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class TimelineMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        cls.manifest = create_demo(cls.root)
        cls.plan = compile_job(cls.manifest)
        cls.movie = cls.root / "editorial.mp4"
        cls.receipt = render(cls.plan, cls.root, cls.movie)
        cls.audio = decoded_audio(cls.movie)

    def test_overlapping_tracks_keep_gain_trim_and_start_time(self) -> None:
        music = tone_level(self.audio, 220, 0.8)
        # The source's first second is silent. Audible music here proves it was trimmed.
        self.assertGreater(music, 0.02)
        self.assertAlmostEqual(music, tone_level(self.audio, 220, 3), delta=music * 0.15)
        self.assertLess(tone_level(self.audio, 660, 1.5), 0.001)
        self.assertGreater(tone_level(self.audio, 660, 3), 0.1)
        self.assertLess(tone_level(self.audio, 660, 6.5), 0.001)
        # -3 dB narration vs -18 dB music; mixing must not auto-normalize the overlap.
        self.assertAlmostEqual(tone_level(self.audio, 660, 3) / music, 10 ** (15 / 20), delta=0.7)

    def test_fades_are_audible_and_mix_does_not_extend_picture(self) -> None:
        full = tone_level(self.audio, 220, 1)
        self.assertLess(tone_level(self.audio, 220, 0.02), full * 0.3)
        self.assertLess(tone_level(self.audio, 220, 7.8), full * 0.3)
        self.assertEqual(self.receipt["frames_observed"], 192)
        self.assertAlmostEqual(self.receipt["duration_observed_seconds"], 8, delta=0.05)
        self.assertAlmostEqual(len(self.audio) / 48000, 8, delta=0.03)
        self.assertEqual(self.receipt["assets"]["music"]["sha256"], self.plan["assets"]["music"]["sha256"])

    def test_caption_frame_boundaries_and_safe_area_across_a_cut(self) -> None:
        frames = [11, 12, 71, 72, 83, 84, 95, 96, 143, 144, 191]
        select = "+".join(f"eq(n,{number})" for number in frames)
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(self.movie), "-vf", f"select='{select}'",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, check=True
        ).stdout
        width, height = 640, 360
        self.assertEqual(len(raw), len(frames) * width * height)
        for index, number in enumerate(frames):
            frame = raw[index * width * height:(index + 1) * width * height]
            foreground = [i for i in range(250 * width, len(frame)) if frame[i] > 200]
            with self.subTest(frame=number):
                if number in (11, 72, 83):
                    self.assertFalse(foreground)
                else:
                    self.assertGreater(len(foreground), 100)
                    self.assertGreaterEqual(min(i % width for i in foreground), 24)
                    self.assertLess(max(i % width for i in foreground), width - 24)
                    self.assertLess(max(i // width for i in foreground), height - 24)

    def test_changed_short_and_non_audio_sources_fail_before_rendering(self) -> None:
        for kind, message in (("changed", "changed since"), ("short", "too short"), ("image", "audio stream")):
            with self.subTest(kind=kind):
                plan = copy.deepcopy(self.plan)
                if kind == "image":
                    path = self.root / "timeline.ppm"
                else:
                    path = self.root / "short.wav"
                    write_tone(path, 220, 0.5)
                plan["assets"]["music"]["path"] = path.name
                if kind != "changed":
                    plan["assets"]["music"]["sha256"] = sha256_file(path)
                output = self.root / f"rejected-{kind}.mp4"
                with self.assertRaisesRegex(ProductionError, message):
                    render(plan, self.root, output)
                self.assertFalse(output.exists())

    def test_embedded_sound_can_be_preserved_or_muted(self) -> None:
        source = self.root / "source.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x360:r=24:d=4",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
             "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
            capture_output=True, check=True
        )
        # The adapter consumes compiled plans; use the same reviewed timeline
        # with a synthetic video source to exercise its embedded-audio policy.
        for policy in ("preserve", "mute"):
            with self.subTest(policy=policy):
                plan = copy.deepcopy(self.plan)
                plan["segments"][0].update(kind="animation", asset_id="clip")
                plan["assets"]["clip"] = {**plan["assets"]["illustration"], "kind": "video",
                                           "path": source.name, "sha256": sha256_file(source)}
                plan["timeline"]["source_audio"] = policy
                plan["timeline"]["source_audio_gain_db"] = -6
                output = self.root / f"{policy}.mp4"
                render(plan, self.root, output)
                audio = decoded_audio(output)
                level = tone_level(audio, 440, 1)
                if policy == "preserve":
                    self.assertAlmostEqual(level, 0.125 * 10 ** (-6 / 20), delta=0.01)
                else:
                    self.assertLess(level, 0.001)
                self.assertGreater(tone_level(audio, 220, 1), 0.02)
                self.assertGreater(tone_level(audio, 660, 3), 0.1)

    def test_audio_and_captions_can_be_used_independently(self) -> None:
        for feature in ("audio", "captions"):
            with self.subTest(feature=feature):
                plan = copy.deepcopy(self.plan)
                if feature == "audio":
                    del plan["timeline"]["captions"]
                else:
                    plan["timeline"]["audio_tracks"] = []
                output = self.root / f"only-{feature}.mp4"
                receipt = render(plan, self.root, output)
                self.assertEqual(receipt["frames_observed"], 192)
                level = tone_level(decoded_audio(output), 660, 3)
                if feature == "audio":
                    self.assertGreater(level, 0.1)
                else:
                    self.assertLess(level, 0.001)


if __name__ == "__main__":
    unittest.main()
