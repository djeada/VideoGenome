"""Library-wide checks: every sample job, scene recipe, bench suite and genome stays usable."""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from videogenome.bench import load_suite
from videogenome.compiler import ROOT, compile_job, read_json
from videogenome.genomes import discover as genomes
from videogenome.procedural import catalog

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_BROWSER = bool(importlib.util.find_spec("playwright"))
EXAMPLES = ROOT / "examples"


class LibraryTests(unittest.TestCase):
    def test_every_sample_job_validates(self) -> None:
        for job in sorted(EXAMPLES.glob("*/job.json")):
            assets = read_json(job).get("assets", {})
            if any(not (job.parent / a["path"]).is_file() for a in assets.values()):
                continue  # Media made by a tool at test time (e.g. tools.create_editorial_demo).
            with self.subTest(job=job.parent.name):
                plan = compile_job(job, allow_pending=True)
                self.assertGreater(plan["total_frames"], 0)

    def test_every_bench_suite_has_an_honest_refusal_case(self) -> None:
        for path in sorted((EXAMPLES / "briefs").glob("*.json")):
            with self.subTest(suite=path.name):
                suite = load_suite(path)
                self.assertTrue(any(b.get("expect") == "incomplete" for b in suite["briefs"]),
                                "every suite should include a brief that lacks a required fact")

    def test_template_level_genomes_have_sample_jobs(self) -> None:
        samples = {read_json(job)["template"] for job in EXAMPLES.glob("*/job.json")}
        for genome in genomes().values():
            if genome.level() != "template":
                continue
            with self.subTest(genome=genome.id):
                templates = set(genome.data["templates"])
                needs_media = bool(genome.data.get("needs"))
                self.assertTrue(templates & samples or needs_media,
                                f"{genome.id}: no sample job for {sorted(templates)}")

    def test_template_looks_must_be_real_presets(self) -> None:
        from videogenome.blueprint import validate_blueprint
        data = json.loads(json.dumps(read_json(ROOT / "templates/social/kinetic-promo/blueprint.json")))
        data["inputs"]["look"]["enum"].append("rainbow")
        self.assertTrue(any("rainbow" in e for e in validate_blueprint(data)))

    def test_editing_a_recipe_invalidates_cached_media(self) -> None:
        from videogenome.produce import _recipe_hashes
        from videogenome.providers.procedural import ProceduralProvider
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "recipes" / "scene" / "probe"
            root.mkdir(parents=True)
            source = ROOT / "recipes/scene/kinetic-type"
            for name in ("index.html", "recipe.json"):
                (root / name).write_text((source / name).read_text().replace("scene.kinetic-type", "scene.probe"))
            import os
            os.environ["VIDEOGENOME_RECIPE_PATH"] = str(Path(directory) / "recipes")
            try:
                chain = [(ProceduralProvider("procedural", {}), "procedural")]
                before = _recipe_hashes(chain, {"recipe": "scene.probe"})
                (root / "index.html").write_text((root / "index.html").read_text() + "\n<!-- edited -->\n")
                after = _recipe_hashes(chain, {"recipe": "scene.probe"})
                self.assertNotEqual(before, after)
            finally:
                del os.environ["VIDEOGENOME_RECIPE_PATH"]

    def test_scene_recipes_declare_clock_timing_and_libraries(self) -> None:
        for recipe in catalog.discover().values():
            if not recipe.id.startswith("scene."):
                continue
            with self.subTest(recipe=recipe.id):
                self.assertEqual(recipe.data.get("timing"), "clock")
                self.assertGreaterEqual(len(recipe.data["presets"]), 3)
                for name, spec in recipe.data["params"]["properties"].items():
                    item = spec.get("items", {}) if spec.get("type") == "array" else spec
                    if item.get("type") == "string" and "enum" not in item and "pattern" not in item:
                        self.assertIn("maxLength", item, f"{name} is copy without a length bound")
                self.assertEqual(len(recipe.sha256()), 64)


@unittest.skipUnless(HAS_FFMPEG and HAS_BROWSER, "FFmpeg and playwright required")
class SceneSmokeTests(unittest.TestCase):
    def test_route_map_counter_fits_small_previews_and_still_rejects_overflow(self) -> None:
        from videogenome.plugins import PluginError
        from videogenome.providers.procedural import ProceduralProvider
        provider = ProceduralProvider("procedural", {})
        request = {"recipe": "scene.route-map", "media": "image", "width": 640, "height": 360,
                   "fps": 24, "duration_seconds": 12.0, "seed": 2}
        with tempfile.TemporaryDirectory() as directory:
            result = provider.generate("procedural", request, Path(directory))
            self.assertGreater(result.path.stat().st_size, 2000)
        with tempfile.TemporaryDirectory() as directory:  # Shrinks to fit its column, down to a legible floor...
            provider.generate("procedural", {**request, "params": {"distance": 100000}}, Path(directory))
        with tempfile.TemporaryDirectory() as directory:  # ...and refuses what cannot fit even there.
            with self.assertRaisesRegex(PluginError, r'counter "99999.99 nmi" does not fit'):
                provider.generate("procedural", {**request, "params": {"distance": 99999.99, "distance_unit": "nmi"}},
                                  Path(directory))

    def test_every_scene_recipe_renders_a_still_in_two_formats(self) -> None:
        from videogenome.providers.procedural import ProceduralProvider
        provider = ProceduralProvider("procedural", {})
        for recipe in catalog.discover().values():
            if not recipe.id.startswith("scene."):
                continue
            for width, height in ((1280, 720), (720, 1280)):
                with self.subTest(recipe=recipe.id, size=f"{width}x{height}"), \
                        tempfile.TemporaryDirectory() as directory:
                    result = provider.generate("procedural", {
                        "recipe": recipe.id, "media": "image", "width": width, "height": height, "fps": 24,
                        "duration_seconds": 12.0, "seed": 2}, Path(directory))
                    self.assertGreater(result.path.stat().st_size, 2000)


if __name__ == "__main__":
    unittest.main()
