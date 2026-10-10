"""Validate VideoGenome JSON blueprints: JSON Schema + cross-field invariants.

This does not render media or execute declared QA gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "blueprint.schema.json"


def load_schema() -> dict:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def validate_blueprint(data: object, schema: dict | None = None) -> list[str]:
    """Return portable, human-readable validation errors."""
    validator = Draft202012Validator(schema or load_schema())
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: str(list(e.absolute_path))):
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{path}: {error.message}")
    if errors:
        return errors

    # JSON Schema cannot conveniently express these relationships.
    assert isinstance(data, dict)
    inputs = set(data["inputs"])
    scene_ids: set[str] = set()
    shot_ids: set[str] = set()
    gate_ids: set[str] = set()
    for scene in data["scenes"]:
        scene_id = scene["id"]
        if scene_id in scene_ids:
            errors.append(f"duplicate scene id: {scene_id}")
        scene_ids.add(scene_id)
        frame_sum = sum(shot["duration_frames"] for shot in scene["shots"])
        if frame_sum != scene["duration_frames"]:
            errors.append(
                f"scene {scene_id}: shot durations sum to {frame_sum}, "
                f"expected {scene['duration_frames']} frames"
            )
        for shot in scene["shots"]:
            shot_id = shot["id"]
            if shot_id in shot_ids:
                errors.append(f"duplicate shot id: {shot_id}")
            shot_ids.add(shot_id)
            for ref in shot.get("input_refs", []):
                if ref not in inputs:
                    errors.append(f"shot {shot_id}: unknown input_ref {ref!r}")
    for gate in data["quality_gates"]:
        if gate["id"] in gate_ids:
            errors.append(f"duplicate quality gate id: {gate['id']}")
        gate_ids.add(gate["id"])
    return errors


def resolve_paths(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        return sorted((ROOT / "templates").glob("**/blueprint.json"))
    expanded: list[Path] = []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            expanded.extend(sorted(path.glob("**/blueprint.json")))
        else:
            expanded.append(path)
    return sorted(set(expanded))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate VideoGenome blueprint files")
    parser.add_argument("paths", nargs="*", help="Blueprint JSON files or directories")
    args = parser.parse_args()
    schema = load_schema()
    paths = resolve_paths(args.paths)
    if not paths:
        print("No blueprints found")
        return 1
    failures = 0
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_blueprint(data, schema)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [str(exc)]
        if errors:
            failures += 1
            print(f"FAIL {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
