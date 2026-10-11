"""Deterministic blueprint discovery for content-filling agents.

Catalog results describe capabilities and required slots; they do not claim a
provider or renderer can create an asset from scratch.
"""
from __future__ import annotations

import json
from math import gcd
from pathlib import Path

from tools.validate import validate_blueprint
from videogenome.compiler import ROOT, ProductionError, read_json


def describe_template(path: Path) -> dict:
    data = read_json(path)
    errors = validate_blueprint(data)
    if errors:
        raise ProductionError(f"Invalid catalog template {path}: {'; '.join(errors)}")
    width, height = data["output"]["width"], data["output"]["height"]
    divisor = gcd(width, height)
    if height > width:
        orientation = "portrait"
    elif width > height:
        orientation = "landscape"
    else:
        orientation = "square"
    kinds = sorted({
        shot["kind"] for scene in data["scenes"] for shot in scene["shots"]
    })
    return {
        "id": data["id"],
        "version": data["version"],
        "title": data["title"],
        "description": data["description"],
        "category": data["category"],
        "tags": data.get("tags", []),
        "engines": data["engines"],
        "shot_kinds": kinds,
        "output": {**data["output"], "orientation": orientation, "aspect_ratio": f"{width//divisor}:{height//divisor}"},
        "required_inputs": {
            name: spec["type"] for name, spec in data["inputs"].items() if spec["required"]
        },
        "optional_inputs": {
            name: spec["type"] for name, spec in data["inputs"].items() if not spec["required"]
        },
        "has_human_gates": any(g["mode"] == "human" for g in data["quality_gates"]),
        "path": str(path.relative_to(ROOT))
    }


def discover(
    *, category: str | None = None, tag: str | None = None,
    orientation: str | None = None, engine: str | None = None,
    shot_kind: str | None = None
) -> list[dict]:
    results = []
    for path in sorted((ROOT / "templates").glob("**/blueprint.json")):
        descriptor = describe_template(path)
        if category and descriptor["category"] != category:
            continue
        if tag and tag not in descriptor["tags"]:
            continue
        if orientation and descriptor["output"]["orientation"] != orientation:
            continue
        if engine and engine not in descriptor["engines"]:
            continue
        if shot_kind and shot_kind not in descriptor["shot_kinds"]:
            continue
        results.append(descriptor)
    return results


def inspect_template(identifier: str) -> dict:
    found = [entry for entry in discover() if entry["id"] == identifier]
    if len(found) != 1:
        raise ProductionError(f"Expected exactly one template named {identifier!r}, found {len(found)}")
    return found[0]


def scaffold(identifier: str, job_path: Path) -> dict:
    """Generate a *non-production-ready* job skeleton to fill and rights-clear.

    No source assets are created, licensed, or invented by this function.
    """
    descriptor = inspect_template(identifier)
    template_path = ROOT / descriptor["path"]
    template = read_json(template_path)
    values = {}
    for name, spec in template["inputs"].items():
        kind = spec["type"]
        if kind in ("string", "url"):
            values[name] = ""
        elif kind in ("string_array", "image_array", "video_array"):
            values[name] = []
        elif kind == "number":
            values[name] = 0
        elif kind == "boolean":
            values[name] = False
        else:
            values[name] = "REPLACE_WITH_RIGHTS_CLEARED_ASSET_ID"
    return {
        "job_schema": "0.1.0",
        "id": "draft.fill-this-in",
        "template": str(template_path.resolve()),
        "template_version": template["version"],
        "inputs": values,
        "assets": {},
        "shot_assets": {},
        "approved_gates": []
    }
