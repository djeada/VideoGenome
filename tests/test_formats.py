"""Delivery formats: one template and one job rendered at several aspect ratios."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate import validate_blueprint
from videogenome.catalog import discover
from videogenome.compiler import ROOT, ProductionError, compile_job, find_template, read_json
from videogenome.fill import check_values, slot_contracts
from videogenome.formats import apply_format, format_ids, job_stem, output_path, resolve

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
HAS_BROWSER = bool(importlib.util.find_spec("playwright"))
HAS_SCIENCE = all(importlib.util.find_spec(name) for name in ("numpy", "scipy"))


def cards_blueprint() -> dict:
    """The title-card sequence at a small size, with a portrait and a square format."""
    data = read_json(ROOT / "templates/educational/title-card-sequence/blueprint.json")
    data.update({"id": "test.cards-formats", "version": "1.0.0", "schema_version": "0.6.0"})
    data["output"].update({"width": 640, "height": 360, "poster_frame": 48})
    data["style"]["title_card"].update({"font_size": 36, "min_font_size": 22, "kicker_font_size": 12,
                                        "safe_margin_x": 64, "safe_margin_top": 48, "safe_margin_bottom": 48})
    data["output"]["formats"] = {
        "9x16": {"width": 360, "height": 640,
                 "title_card": {"font_size": 30, "min_font_size": 20, "safe_margin_x": 60}},
        "1x1": {"width": 480, "height": 480},
    }
    data.pop("copy_examples", None)
    return data


def write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    return stream["width"], stream["height"]


class FormatContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blueprint = cards_blueprint()

    def test_fixture_and_every_format_validate(self) -> None:
        self.assertEqual(validate_blueprint(self.blueprint), [])
        self.assertEqual(format_ids(self.blueprint), ["16x9", "9x16", "1x1"])

    def test_rejects_inconsistent_formats(self) -> None:
        for patch, message in (
            ({"9x16": {"width": 360, "height": 360}}, "is 1:1, not 9:16"),
            ({"16x9": {"width": 1280, "height": 720}}, "duplicates the main output format"),
            ({"4x5": {"width": 1080, "height": 1350}, "1x1": {"width": 481, "height": 481}}, "even frame"),
        ):
            with self.subTest(patch=patch):
                data = copy.deepcopy(self.blueprint)
                data["output"]["formats"] = patch
                self.assertTrue(any(message in e for e in validate_blueprint(data)), validate_blueprint(data))

    def test_formats_need_schema_0_6(self) -> None:
        self.blueprint["schema_version"] = "0.5.0"
        self.assertIn("output.formats requires schema_version 0.6.0", validate_blueprint(self.blueprint))

    def test_overrides_need_what_they_override(self) -> None:
        del self.blueprint["style"]["title_card"]
        errors = validate_blueprint(self.blueprint)
        self.assertTrue(any("title_card overrides need a declared style.title_card" in e for e in errors), errors)

    def test_each_format_is_validated_at_its_own_size(self) -> None:
        # Margins that suit the main frame leave no room in a narrow one.
        self.blueprint["output"]["formats"]["9x16"]["title_card"]["safe_margin_x"] = 160
        errors = validate_blueprint(self.blueprint)
        self.assertTrue(any(e.startswith("format 9:16: title_card horizontal margins") for e in errors), errors)

    def test_apply_format_copies_geometry_and_overrides(self) -> None:
        tall = apply_format(self.blueprint, "9:16")
        self.assertEqual((tall["output"]["width"], tall["output"]["height"]), (360, 640))
        self.assertEqual(tall["style"]["title_card"]["font_size"], 30)
        self.assertEqual(tall["style"]["title_card"]["background"], self.blueprint["style"]["title_card"]["background"])
        self.assertNotIn("formats", tall["output"])
        main = apply_format(self.blueprint)
        self.assertEqual(main["output"]["width"], 640)
        self.assertNotIn("formats", main["output"])
        self.assertIn("formats", self.blueprint["output"])  # The source is untouched.
        with self.assertRaisesRegex(ProductionError, "has no 4:5 format; it renders 16:9, 9:16, 1:1"):
            apply_format(self.blueprint, "4x5")

    def test_resolve_and_naming(self) -> None:
        self.assertEqual(resolve(self.blueprint, None), ["16x9"])
        self.assertEqual(resolve(self.blueprint, ["all"]), ["16x9", "9x16", "1x1"])
        self.assertEqual(resolve(self.blueprint, ["1:1,9x16", "1x1"]), ["1x1", "9x16"])
        with self.assertRaises(ProductionError):
            resolve(self.blueprint, ["21x9"])
        self.assertEqual(output_path(Path("out/promo.mp4"), "9x16", True), Path("out/promo.9x16.mp4"))
        self.assertEqual(output_path(Path("out/promo.mp4"), "9x16", False), Path("out/promo.mp4"))
        self.assertEqual(job_stem(Path("job.9x16.produced.json")), "job")
        self.assertEqual(job_stem(Path("job.produced.json")), "job")
        self.assertEqual(job_stem(Path("my.job.json")), "my.job")

    def test_copy_budget_is_the_tightest_format(self) -> None:
        single = copy.deepcopy(self.blueprint)
        del single["output"]["formats"]
        wide = slot_contracts(single)["headline"]["max_chars"]
        every = slot_contracts(self.blueprint)["headline"]
        self.assertLess(every["max_chars"], wide)
        self.assertTrue(any("format]" in use for use in every["uses"]), every["uses"])

    def test_layout_problems_name_the_format(self) -> None:
        contracts = slot_contracts(self.blueprint)
        # A long word fits the 16:9 and 1:1 frames but not the narrow 9:16 one.
        values = {"headline": "Pneumonoultramicroscopic", "insight": "One idea.", "action": "Go"}
        issues = check_values(self.blueprint, contracts, values, "")
        self.assertTrue(issues)
        self.assertTrue(all(i["problem"].startswith("in the 9:16 format:") for i in issues), issues)

    def test_catalog_lists_formats_and_filters_by_any_orientation(self) -> None:
        entries = {e["id"]: e for e in discover(orientation="portrait")}
        self.assertIn("educational.how-it-works", entries)  # 16:9 main, renders 9:16 too.
        ratios = [f["aspect_ratio"] for f in entries["educational.how-it-works"]["formats"]]
        self.assertEqual(ratios[0], "16:9")
        self.assertIn("9:16", ratios)

    def test_scene_templates_declare_their_formats(self) -> None:
        for template in ("commercial.stat-highlights", "social.quote-loop", "educational.chart-story"):
            with self.subTest(template=template):
                self.assertGreater(len(format_ids(read_json(find_template(template)))), 1)


class FormatJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.templates = self.root / "templates"
        write(self.templates / "cards" / "blueprint.json", cards_blueprint())
        self.job = write(self.root / "job" / "job.json", {
            "job_schema": "0.1.0", "id": "test.formats", "template": "test.cards-formats",
            "template_version": "1.0.0",
            "inputs": {"headline": "Design once", "insight": "Every frame fits", "action": "Ship it"},
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_compile_in_each_format(self) -> None:
        plans = {f: compile_job(self.job, template_dirs=[self.templates], format=f) for f in ("16x9", "9x16", "1x1")}
        self.assertEqual({f: (p["output"]["width"], p["output"]["height"]) for f, p in plans.items()},
                         {"16x9": (640, 360), "9x16": (360, 640), "1x1": (480, 480)})
        self.assertEqual({f: p["format"] for f, p in plans.items()}, {f: f for f in plans})
        self.assertEqual(plans["9x16"]["title_card"]["font_size"], 30)
        self.assertNotIn("formats", plans["16x9"]["output"])
        self.assertEqual(compile_job(self.job, template_dirs=[self.templates])["format"], "16x9")

    def test_job_format_field_and_produced_media_pin_the_format(self) -> None:
        job = read_json(self.job)
        job["format"] = "1x1"
        write(self.job, job)
        self.assertEqual(compile_job(self.job, template_dirs=[self.templates])["output"]["width"], 480)
        # Media produced at one frame size never renders in another.
        frame = self.job.parent / "backdrop.png"
        frame.write_bytes(b"\x89PNG\r\n\x1a\n")
        job["assets"] = {"backdrop": {"kind": "image", "path": "backdrop.png",
                                      "origin": {"type": "rendered", "description": "test frame"},
                                      "rights": {"cleared": True, "license": "MIT", "evidence": "test"},
                                      "generation": {"capability": "procedural", "pipeline": "x",
                                                     "providers": ["p"], "placeholder": True}}}
        write(self.job, job)
        with self.assertRaisesRegex(ProductionError, "produced for the 1:1 format"):
            compile_job(self.job, template_dirs=[self.templates], format="9x16")

    def test_unknown_job_format_is_refused(self) -> None:
        job = read_json(self.job)
        job["format"] = "4x5"
        write(self.job, job)
        with self.assertRaisesRegex(ProductionError, "has no 4:5 format"):
            compile_job(self.job, template_dirs=[self.templates])

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
    def test_cli_renders_every_format_from_one_job(self) -> None:
        out = self.root / "out" / "cards.mp4"
        completed = subprocess.run(
            [sys.executable, "-m", "videogenome", "render", str(self.job), "--templates", str(self.templates),
             "--format", "all", "-o", str(out), "--receipt", str(self.root / "out" / "receipt.json"),
             "--no-deliverables"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        sizes = {"16x9": (640, 360), "9x16": (360, 640), "1x1": (480, 480)}
        for format_id, size in sizes.items():
            with self.subTest(format=format_id):
                video = out.with_name(f"cards.{format_id}.mp4")
                self.assertEqual(probe_size(video), size)
                receipt = read_json(self.root / "out" / f"receipt.{format_id}.json")
                self.assertEqual(receipt["format"], format_id)
                self.assertEqual(receipt["frames_observed"], 216)
        self.assertFalse(out.exists())

    @unittest.skipUnless(HAS_FFMPEG and HAS_SCIENCE, "FFmpeg, numpy and scipy required")
    def test_produce_per_format_reuses_frame_independent_media(self) -> None:
        from videogenome.produce import produce
        from videogenome.profile import Profile
        profile = Profile.load("procedural")
        main, report = produce(self.job, profile, template_dirs=[self.templates])
        self.assertEqual(main.name, "job.produced.json")
        self.assertEqual({e["input"]: e["status"] for e in report}, {"backdrop": "generated", "music": "generated"})
        tall, report = produce(self.job, profile, template_dirs=[self.templates], format="9:16")
        self.assertEqual(tall.name, "job.9x16.produced.json")
        status = {e["input"]: e for e in report}
        self.assertEqual(status["backdrop"]["status"], "generated")
        self.assertEqual(status["backdrop"]["path"], "generated/9x16/backdrop.mp4")
        self.assertEqual(status["music"]["status"], "reused")  # Sound does not depend on the frame.
        self.assertEqual(status["music"]["path"], "generated/music.wav")
        self.assertEqual(read_json(tall)["format"], "9x16")
        self.assertNotIn("format", read_json(main))
        plan = compile_job(tall, template_dirs=[self.templates])
        self.assertEqual((plan["output"]["width"], plan["output"]["height"]), (360, 640))
        backdrop = plan["assets"]["backdrop"]["path"]
        self.assertEqual(probe_size(self.job.parent / backdrop), (360, 640))
        _, again = produce(self.job, profile, template_dirs=[self.templates], format="9x16")
        self.assertEqual({e["status"] for e in again}, {"cached"})


@unittest.skipUnless(HAS_BROWSER, "playwright required")
class LayoutCheckTests(unittest.TestCase):
    """Real recipes, real browser: copy that fits one frame and not another is caught before rendering."""

    def test_reports_the_slot_and_format_that_do_not_fit(self) -> None:
        from videogenome.layout_check import layout_issues
        blueprint = read_json(find_template("educational.chart-story"))
        # Squeeze the chart-story copy into a square frame it is not offered in.
        blueprint["output"]["formats"]["1x1"] = {"width": 1080, "height": 1080}
        inputs = read_json(ROOT / "examples/chart-story/job.json")["inputs"]
        issues = layout_issues(blueprint, inputs)
        self.assertTrue(issues)
        self.assertTrue(all(i["formats"] == ["1x1"] and i["kind"] == "layout" for i in issues), issues)
        self.assertTrue(all(i["problem"].startswith("in the 1:1 format: scene (scene.chart-story)") for i in issues))
        self.assertTrue(all(set(i["slots"]) <= {"title", "subtitle", "takeaway", "source", "labels"} or i["slots"]
                            for i in issues))
        self.assertEqual(layout_issues(blueprint, inputs, ["16x9", "9x16"]), [])

    def test_every_template_format_fits_its_sample_and_examples(self) -> None:
        """A template may list a format only if its sample job and copy examples fit it."""
        from videogenome.layout_check import layout_issues_many
        samples = {}
        for path in sorted((ROOT / "examples").glob("*/job.json")):
            job = read_json(path)
            samples.setdefault(job["template"], job["inputs"])
        cases, names = [], []
        for path in sorted((ROOT / "templates").glob("**/blueprint.json")):
            blueprint = read_json(path)
            if not blueprint["output"].get("formats"):
                continue
            for name, inputs in ([("sample", samples[blueprint["id"]])] if blueprint["id"] in samples else []) + [
                    (f"copy_examples[{i}]", e["inputs"]) for i, e in enumerate(blueprint.get("copy_examples", []))]:
                cases.append((blueprint, inputs, None))
                names.append(f"{blueprint['id']} {name}")
        self.assertGreater(len(cases), 20)
        for name, issues in zip(names, layout_issues_many(cases)):
            with self.subTest(case=name):
                self.assertEqual(issues, [])

    def test_check_inputs_reports_layout_only_when_the_pipeline_renders_recipes(self) -> None:
        from videogenome.profile import Profile
        from videogenome.service import Service, Workspace
        with tempfile.TemporaryDirectory() as directory:
            inputs = read_json(ROOT / "examples/stat-highlights/job.json")["inputs"]
            animatic = Service(Profile.load("animatic"), Workspace(Path(directory)))
            result = animatic.check_inputs("commercial.stat-highlights", inputs, layout=True)
            self.assertFalse(result["layout_checked"])
            self.assertIn("does not render code recipes", result["note"])
            procedural = Service(Profile.load("procedural"), Workspace(Path(directory)))
            result = procedural.check_inputs("commercial.stat-highlights", inputs, layout=True)
            self.assertTrue(result["layout_checked"])
            self.assertEqual(result["formats"], ["9:16", "16:9", "1:1"])


if __name__ == "__main__":
    unittest.main()
