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
        social = discover(category="social", orientation="portrait")
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

    def test_unknown_template_rejected(self) -> None:
        with self.assertRaises(ProductionError):
            inspect_template("missing.template")


if __name__ == "__main__":
    unittest.main()
