"""Agents can discover an expanding catalog without hard-coded template counts."""
from __future__ import annotations

import json
import unittest

from videogenome.catalog import discover, inspect_template, scaffold
from videogenome.compiler import ProductionError


class CatalogTests(unittest.TestCase):
    def test_discovers_multiple_video_formats(self) -> None:
        catalog = discover()
        self.assertGreaterEqual(len(catalog), 5)
        categories = {entry["category"] for entry in catalog}
        self.assertTrue({"social", "commercial", "educational"}.issubset(categories))
        self.assertEqual(len({entry["id"] for entry in catalog}), len(catalog))

    def test_filters_exact_metadata_without_inventing_capabilities(self) -> None:
        social = discover(category="social", orientation="portrait", shot_kind="talking_head")
        self.assertEqual(len(social), 1)
        self.assertIn("talking_head", social[0]["shot_kinds"])
        self.assertIn("speaker_clip", social[0]["required_inputs"])
        self.assertEqual(discover(engine="nonexistent-provider"), [])

    def test_inspect_and_scaffold(self) -> None:
        descriptor = inspect_template("educational.title-card-sequence")
        self.assertEqual(descriptor["output"]["orientation"], "landscape")
        draft = scaffold(descriptor["id"], None)
        self.assertEqual(draft["inputs"]["headline"], "")
        self.assertEqual(draft["template_version"], descriptor["version"])
        self.assertEqual(draft["assets"], {})
        self.assertEqual(draft["template"], "educational.title-card-sequence")

    def test_scaffold_lists_only_required_inputs(self) -> None:
        draft = scaffold("social.vertical-tips")
        self.assertNotIn("music", draft["inputs"])
        self.assertEqual(set(draft["inputs"]), {"hook", "tip_1", "tip_2", "tip_3", "cta"})

    def test_self_contained_templates_render_from_text_alone(self) -> None:
        ids = {entry["id"] for entry in discover(self_contained=True)}
        self.assertIn("educational.title-card-sequence", ids)
        self.assertIn("social.vertical-tips", ids)
        self.assertNotIn("educational.captioned-explainer", ids)

    def test_unknown_template_rejected(self) -> None:
        with self.assertRaises(ProductionError):
            inspect_template("missing.template")

    def test_editorial_template_exposes_locked_caption_and_audio_requirements(self) -> None:
        descriptor = inspect_template("educational.captioned-explainer")
        self.assertEqual(descriptor["schema_version"], "0.2.0")
        self.assertEqual(descriptor["required_inputs"]["narration"], "audio")
        self.assertEqual(descriptor["timeline"]["captions"]["style"]["max_lines"], 2)
        self.assertEqual(descriptor["timeline"]["audio_tracks"][1]["start_frame"], 48)


if __name__ == "__main__":
    unittest.main()
