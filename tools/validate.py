"""Validate VideoGenome JSON blueprints: JSON Schema + cross-field invariants.

This does not render media or execute declared QA gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from videogenome.blueprint import SCHEMA_PATH, load_schema, validate_blueprint
from videogenome.resources import BUILTIN_TEMPLATES, DATA_ROOT

ROOT = DATA_ROOT
__all__ = ["ROOT", "SCHEMA_PATH", "load_schema", "validate_blueprint", "resolve_paths", "main"]


def resolve_paths(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        return sorted(BUILTIN_TEMPLATES.glob("**/blueprint.json"))
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
