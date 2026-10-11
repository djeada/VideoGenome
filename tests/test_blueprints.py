"""Contract and semantic validation tests for the example blueprints."""
from __future__ import annotations

import copy
import json
import unittest

from tools.validate import ROOT, load_schema, validate_blueprint


class BlueprintValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()
        cls.paths = sorted((ROOT / "templates").glob("**/blueprint.json"))
        cls.good = json.loads(cls.paths[0].read_text(encoding="utf-8"))

    def test_examples_validate(self) -> None:
        self.assertEqual(len(self.paths), 3)
        for path in self.paths:
            with self.subTest(path=path):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate_blueprint(data, self.schema), [])

    def test_rejects_unknown_input_ref(self) -> None:
        data = copy.deepcopy(self.good)
        data["scenes"][0]["shots"][0]["input_refs"] = ["not_declared"]
        self.assertTrue(any("unknown input_ref" in e for e in validate_blueprint(data, self.schema)))

    def test_rejects_duration_mismatch(self) -> None:
        data = copy.deepcopy(self.good)
        data["scenes"][0]["duration_frames"] += 1
        self.assertTrue(any("shot durations sum" in e for e in validate_blueprint(data, self.schema)))

    def test_rejects_duplicate_shot_id(self) -> None:
        data = copy.deepcopy(self.good)
        data["scenes"][1]["shots"][0]["id"] = data["scenes"][0]["shots"][0]["id"]
        self.assertTrue(any("duplicate shot id" in e for e in validate_blueprint(data, self.schema)))

    def test_rejects_wrong_type(self) -> None:
        data = copy.deepcopy(self.good)
        data["output"]["fps"] = "thirty"
        self.assertTrue(validate_blueprint(data, self.schema))

    def test_rejects_duplicate_gate_id(self) -> None:
        data = copy.deepcopy(self.good)
        data["quality_gates"][1]["id"] = data["quality_gates"][0]["id"]
        self.assertTrue(any("duplicate quality gate id" in e for e in validate_blueprint(data, self.schema)))


if __name__ == "__main__":
    unittest.main()
