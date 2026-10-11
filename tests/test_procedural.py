"""Procedural recipes, retrieval providers and the v0.4 mix/picture features."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from videogenome.blueprint import validate_blueprint
from videogenome.compiler import ROOT, ProductionError, compile_job
from videogenome.plugins import PluginError
from videogenome.procedural import catalog

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_SCIENCE = all(importlib.util.find_spec(m) for m in ("numpy", "scipy"))
HAS_BROWSER = bool(importlib.util.find_spec("playwright"))
CARDS = ROOT / "templates/educational/title-card-sequence/blueprint.json"
SLIDES = ROOT / "templates/educational/narrated-slides/blueprint.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CatalogTests(unittest.TestCase):
    def test_shipped_recipes_are_valid_and_documented(self) -> None:
        recipes = catalog.discover()
        self.assertTrue({"visual.aurora", "visual.shader-gradient", "audio.ambient-pad"} <= set(recipes))
        for recipe in recipes.values():
            with self.subTest(recipe=recipe.id):
                self.assertEqual(recipe.data["license"], "MIT")
                for name, spec in recipe.data["params"]["properties"].items():
                    self.assertIn("description", spec, name)
                for preset in recipe.data.get("presets", {}):
                    recipe.resolve(preset)

    def test_resolution_order_and_validation(self) -> None:
        recipe = catalog.get("visual.aurora")
        self.assertEqual(recipe.resolve()["speed"], recipe.data["params"]["properties"]["speed"]["default"])
        self.assertEqual(recipe.resolve("vivid")["palette"][0], "#120B2E")
        self.assertEqual(recipe.resolve("vivid", {"speed": 0.5})["speed"], 0.5)
        for params, message in (({"speed": 99}, "maximum"), ({"colour": "red"}, "Additional"),
                                ({"palette": ["red"]}, "")):
            with self.subTest(params=params), self.assertRaisesRegex(ProductionError, message):
                recipe.resolve(None, params)
        with self.assertRaisesRegex(ProductionError, "no preset"):
            recipe.resolve("neon")
        with self.assertRaisesRegex(ProductionError, "Unknown recipe"):
            catalog.get("visual.nope")

    def test_invalid_recipe_manifests_are_rejected(self) -> None:
        good = load(ROOT / "recipes/visual/aurora/recipe.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "aurora.py").write_text("", encoding="utf-8")
            broken = copy.deepcopy(good)
            del broken["params"]["properties"]["speed"]["description"]
            self.assertTrue(catalog.recipe_errors(broken, root))
            broken = copy.deepcopy(good)
            broken["presets"]["bad"] = {"speed": -1}
            self.assertTrue(any("preset bad" in e for e in catalog.recipe_errors(broken, root)))
            broken = copy.deepcopy(good)
            broken["entry"] = "missing.py"
            self.assertTrue(any("does not exist" in e for e in catalog.recipe_errors(broken, root)))

    def test_blueprints_must_name_real_recipes_presets_and_params(self) -> None:
        data = load(CARDS)
        request = data["inputs"]["backdrop"]["produce"]["request"]
        self.assertEqual(validate_blueprint(data), [])
        for patch, message in (({"recipe": "visual.nope"}, "Unknown recipe"),
                               ({"preset": "neon"}, "no preset"),
                               ({"params": {"sparkles": 3}}, "no params")):
            with self.subTest(patch=patch):
                broken = copy.deepcopy(data)
                broken["inputs"]["backdrop"]["produce"]["request"] = {**request, **patch}
                self.assertTrue(any(message in e for e in validate_blueprint(broken)))


@unittest.skipUnless(HAS_FFMPEG and HAS_SCIENCE, "FFmpeg, numpy and scipy required")
class RecipeRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def render(self, request: dict, name: str):
        from videogenome.providers.procedural import ProceduralProvider
        work = self.root / name
        work.mkdir()
        return ProceduralProvider("procedural", {}).generate("procedural", request, work)

    def test_python_visual_is_deterministic_and_exact(self) -> None:
        from videogenome.render import probe
        request = {"recipe": "visual.aurora", "preset": "calm", "media": "video", "width": 160,
                   "height": 90, "fps": 12, "duration_seconds": 0.5, "seed": 4}
        first, second = self.render(request, "a"), self.render(request, "b")
        frames = [s for s in probe(first.path, count_frames=True)["streams"] if s["codec_type"] == "video"]
        self.assertEqual(int(frames[0]["nb_read_frames"]), 6)
        self.assertEqual(digest(first.path), digest(second.path))
        self.assertEqual(first.metadata["rights"]["license"], "MIT")
        self.assertEqual(first.metadata["recipe"]["preset"], "calm")
        third = self.render({**request, "seed": 5}, "c")
        self.assertNotEqual(digest(first.path), digest(third.path))

    def test_every_audio_recipe_renders_at_bed_loudness(self) -> None:
        from videogenome.procedural import dsp
        import numpy as np
        import wave
        for recipe in [r for r in catalog.discover().values() if "audio" in r.data["media"]]:
            with self.subTest(recipe=recipe.id):
                result = self.render({"recipe": recipe.id, "media": "audio", "duration_seconds": 3.0,
                                      "seed": 2}, recipe.id)
                with wave.open(str(result.path)) as handle:
                    raw = np.frombuffer(handle.readframes(handle.getnframes()), np.uint8).reshape(-1, 3)
                    self.assertEqual(handle.getnframes(), 3 * 48000)
                samples = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
                           | (raw[:, 2].astype(np.int8).astype(np.int32) << 16)).reshape(-1, 2) / 2 ** 23
                self.assertLess(np.max(np.abs(samples)), 0.95)  # Headroom, never clipped.
                self.assertGreater(dsp.loudness_lufs(samples.astype(np.float32)), -32)

    def test_loudness_meter_matches_ffmpeg(self) -> None:
        from videogenome.procedural import dsp, kit
        import numpy as np
        rng = np.random.default_rng(1)
        audio = dsp.lowpass(rng.standard_normal((48000 * 3, 2)).astype(np.float32) * 0.1, 3000)
        path = self.root / "noise.wav"
        kit.write_wav(path, audio)
        log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                              "-f", "null", "-"], capture_output=True, text=True).stderr
        ffmpeg_value = float(log[log.rfind("Summary:"):].split("I:")[1].split("LUFS")[0])
        self.assertAlmostEqual(dsp.loudness_lufs(audio), ffmpeg_value, delta=0.15)

    @unittest.skipUnless(HAS_BROWSER, "playwright required")
    def test_browser_recipe_renders_frames(self) -> None:
        try:
            result = self.render({"recipe": "visual.shader-gradient", "media": "image", "width": 160,
                                  "height": 90, "seed": 3}, "shader")
        except PluginError as exc:
            self.skipTest(f"Chromium unavailable: {exc}")
        self.assertTrue(result.path.read_bytes().startswith(b"\x89PNG"))

    def test_default_recipes_serve_plain_capabilities_with_style_presets(self) -> None:
        from videogenome.providers.procedural import ProceduralProvider
        provider = ProceduralProvider("p", {"defaults": {"music": {"recipe": "audio.ambient-pad",
                                                                   "preset": "hopeful"}}})
        self.assertEqual(provider.serves(), frozenset({"procedural", "music"}))
        work = self.root / "m"
        work.mkdir()
        result = provider.generate("music", {"duration_seconds": 1.0, "style": "serious", "media": "audio"}, work)
        self.assertEqual(result.metadata["recipe"]["preset"], "serious")
        work = self.root / "n"
        work.mkdir()
        result = provider.generate("music", {"duration_seconds": 1.0, "style": "not-a-preset"}, work)
        self.assertEqual(result.metadata["recipe"]["preset"], "hopeful")


class TimingTests(unittest.TestCase):
    def test_produced_media_is_timed_from_the_locked_timeline(self) -> None:
        from videogenome.produce import timing_needs
        vertical = load(ROOT / "templates/social/vertical-tips/blueprint.json")
        self.assertAlmostEqual(timing_needs(vertical, "backdrop"), 13.5)   # spans every card
        self.assertAlmostEqual(timing_needs(vertical, "whoosh"), 0.8)      # one track window
        self.assertAlmostEqual(timing_needs(vertical, "music"), 13.5)
        documentary = load(ROOT / "templates/educational/cc0-documentary/blueprint.json")
        self.assertAlmostEqual(timing_needs(documentary, "clip_1"), 6.0)   # shot + crossfade handle
        self.assertAlmostEqual(timing_needs(documentary, "voice_1"), 4.5)  # 108-frame narration window
        self.assertIsNone(timing_needs(documentary, "title"))


class StockProviderTests(unittest.TestCase):
    """Licence filtering and provenance, with the network replaced by fixtures."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    @staticmethod
    def fake_download(url, destination, **_):
        destination.write_bytes(b"media:" + url.encode())
        return destination

    def test_openverse_keeps_only_cc0_or_pd_and_records_the_source(self) -> None:
        from videogenome.providers.stock import OpenverseProvider
        results = {"results": [
            {"id": "a", "license": "by", "url": "https://x/a.jpg", "width": 4000, "title": "attribution only"},
            {"id": "b", "license": "cc0", "url": "https://x/b.jpg", "width": 300, "title": "too small"},
            {"id": "c", "license": "cc0", "license_version": "1.0", "url": "https://x/c.jpg", "width": 2400,
             "title": "Lighthouse at dusk", "creator": "Jo", "foreign_landing_url": "https://flickr/c"},
            {"id": "d", "license": "pdm", "url": "https://x/d.jpg", "width": 2400, "title": "Company logo"},
        ]}
        provider = OpenverseProvider("ov", {"exclude_terms": ["logo"], "candidates": 5})
        with mock.patch("videogenome.providers.stock.http_json", return_value=results) as search, \
                mock.patch("videogenome.providers.stock.download", side_effect=self.fake_download):
            result = provider.generate("image", {"query": "lighthouse", "width": 1280, "height": 720, "seed": 0},
                                       self.root)
        url = search.call_args[0][1]
        self.assertIn("license=cc0%2Cpdm", url)
        self.assertIn("aspect_ratio=wide", url)
        self.assertEqual(result.metadata["attribution"]["title"], "Lighthouse at dusk")
        self.assertEqual(result.metadata["rights"]["license"], "CC0 1.0")
        self.assertIn("https://flickr/c", result.metadata["rights"]["evidence"])
        with mock.patch("videogenome.providers.stock.http_json", return_value={"results": results["results"][:2]}):
            with self.assertRaisesRegex(PluginError, "No openly licensed match"):
                provider.generate("image", {"query": "x", "width": 1280, "height": 720}, self.root)

    def test_commons_filters_licences_restrictions_and_duration(self) -> None:
        from videogenome.providers.stock import WikimediaCommonsProvider

        def page(index, title, licence, duration, restrictions="", derivatives=None):
            return {"index": index, "title": title, "videoinfo": [{
                "duration": duration, "width": 1920, "url": f"https://upload/{index}.webm", "size": 10_000,
                "descriptionurl": f"https://commons/{index}", "derivatives": derivatives or [],
                "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": "<b>NASA</b>"},
                                "Restrictions": {"value": restrictions}}}]}
        pages = {"1": page(1, "File:Share alike.webm", "CC BY-SA 4.0", 30),
                 "2": page(2, "File:Too short.webm", "CC0", 2),
                 "3": page(3, "File:Person.webm", "CC0", 30, restrictions="personality"),
                 "4": page(4, "File:Earth.webm", "Public domain", 30,
                           derivatives=[{"src": "https://upload/4.480.webm", "type": "video/webm", "height": 480},
                                        {"src": "https://upload/4.720.webm", "type": "video/webm", "height": 720}])}
        provider = WikimediaCommonsProvider("commons", {})
        with mock.patch("videogenome.providers.stock.http_json", return_value={"query": {"pages": pages}}), \
                mock.patch("videogenome.providers.stock.download", side_effect=self.fake_download) as fetch:
            result = provider.generate("video", {"query": "earth", "width": 1280, "height": 720,
                                                 "duration_seconds": 6.0}, self.root)
        self.assertEqual(fetch.call_args[0][0], "https://upload/4.720.webm")
        self.assertEqual(result.metadata["rights"]["license"], "Public domain")
        self.assertEqual(result.metadata["attribution"]["creator"], "NASA")


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg required")
class MixAndPictureTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _template(self, mutate) -> Path:
        blueprint = load(CARDS)
        blueprint["id"] = "test.cards"
        mutate(blueprint)
        return write(self.root / "templates" / "cards" / "blueprint.json", blueprint)

    def _job(self, **extra) -> Path:
        job = load(ROOT / "examples/three-card-explainer/job.json")
        job["template"] = "test.cards"
        job.update(extra)
        return write(self.root / "job.json", job)

    def test_input_enum_and_default(self) -> None:
        self._template(lambda b: None)
        plan_dirs = [self.root / "templates"]
        job = load(ROOT / "examples/three-card-explainer/job.json")
        job["template"] = "test.cards"
        job["inputs"]["mood"] = "furious"
        with self.assertRaisesRegex(ProductionError, "must be one of"):
            compile_job(write(self.root / "job.json", job), template_dirs=plan_dirs)
        del job["inputs"]["mood"]
        compile_job(write(self.root / "job.json", job), template_dirs=plan_dirs)

    def test_ducking_lowers_music_inside_narration_windows(self) -> None:
        from tools.create_editorial_demo import write_tone

        def mutate(b):
            b["inputs"]["voice"] = {"type": "audio", "required": True, "description": "voice track"}
            b["timeline"]["audio_tracks"] = [
                {"id": "music_bed", "input_ref": "music", "start_frame": 0, "duration_frames": 216},
                {"id": "voice", "input_ref": "voice", "start_frame": 72, "duration_frames": 72}]
            b["timeline"]["ducking"] = [{"track": "music_bed", "under": ["voice"], "depth_db": 12,
                                         "ramp_frames": 6}]
            del b["output"]["loudness"]
        self._template(mutate)
        write_tone(self.root / "music.wav", 220, 10)
        (self.root / "silence.wav").write_bytes(b"")
        write_tone(self.root / "voice.wav", 0.0001, 4)  # Near-silent "voice": only ducking changes level.
        rights = {"cleared": True, "license": "MIT", "evidence": "test tone"}
        assets = {name: {"kind": "audio", "path": f"{name}.wav", "rights": rights,
                         "origin": {"type": "rendered", "description": "test tone"}} for name in ("music", "voice")}
        manifest = self._job(assets=assets, inputs={**load(ROOT / "examples/three-card-explainer/job.json")["inputs"],
                                                    "music": "music", "voice": "voice"})
        plan = compile_job(manifest, template_dirs=[self.root / "templates"])
        self.assertEqual(plan["timeline"]["ducking"][0]["windows"], [[72, 144]] if isinstance(
            plan["timeline"]["ducking"][0]["windows"][0], list) else [(72, 144)])
        from videogenome.render import render
        movie = self.root / "ducked.mp4"
        render(plan, self.root, movie, write_deliverables=False)

        def rms(start: float, length: float) -> float:
            import array
            import math
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(movie),
                                  "-ac", "1", "-f", "s16le", "-"], capture_output=True, check=True).stdout
            values = array.array("h", raw)
            return math.sqrt(sum(v * v for v in values) / len(values))
        import math
        drop = 20 * math.log10(rms(1.0, 1.5) / rms(4.0, 1.5))
        self.assertAlmostEqual(drop, 12, delta=1.5)

    def test_card_background_and_still_motion(self) -> None:
        def mutate(b):
            b["style"]["title_card"]["background_dim"] = 0.5
            b["inputs"]["backdrop"] = {"type": "image", "required": False, "description": "still backdrop"}
        self._template(mutate)
        # A pure red still as the card background.
        (self.root / "red.ppm").write_bytes(b"P6\n4 4\n255\n" + bytes([230, 20, 20] * 16))
        rights = {"cleared": True, "license": "MIT", "evidence": "test"}
        assets = {"red": {"kind": "image", "path": "red.ppm", "rights": rights,
                          "origin": {"type": "rendered", "description": "test"}}}
        inputs = {**load(ROOT / "examples/three-card-explainer/job.json")["inputs"], "backdrop": "red"}
        self.assertEqual(validate_blueprint(load(self.root / "templates/cards/blueprint.json")), [])
        plan = compile_job(self._job(assets=assets, inputs=inputs), template_dirs=[self.root / "templates"])
        self.assertEqual(plan["title_card"]["background_asset"], "red")
        from videogenome.render import render
        movie = self.root / "bg.mp4"
        render(plan, self.root, movie, write_deliverables=False)
        pixel = subprocess.run(["ffmpeg", "-v", "error", "-i", str(movie), "-vf", "select='eq(n,40)',crop=2:2:6:6",
                                "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               capture_output=True, check=True).stdout
        red, green, blue = pixel[:3]
        self.assertGreater(red, 80)       # Background shows through...
        self.assertLess(red, 200)         # ...dimmed by the 50% scrim.
        self.assertLess(green, 40)

        motion_blueprint = load(SLIDES)
        motion_blueprint["inputs"]["slide_1_image"].pop("produce")
        shot = motion_blueprint["scenes"][1]["shots"][0]
        self.assertEqual(shot["motion"]["type"], "push_in")
        from videogenome.render import _motion_filter
        expression = _motion_filter(1280, 720, 24, 144, "cover", shot["motion"])
        self.assertIn("zoompan", expression)
        self.assertIn("5120:2880", expression)


if __name__ == "__main__":
    unittest.main()
