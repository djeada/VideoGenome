"""Deterministic blueprint discovery for content-filling agents.

Catalog results describe capabilities and required slots; they do not claim a
provider or renderer can create an asset from scratch.
"""
from __future__ import annotations

from math import gcd
from pathlib import Path
from typing import Iterable

from videogenome.blueprint import validate_blueprint
from videogenome.compiler import ROOT, ProductionError, read_json
from videogenome.formats import label, main_format
from videogenome.resources import template_roots

ASSET_TYPES = {"image", "image_array", "video", "video_array", "audio"}


def describe_template(path: Path) -> dict:
    data = read_json(path)
    errors = validate_blueprint(data)
    if errors:
        raise ProductionError(f"Invalid catalog template {path}: {'; '.join(errors)}")
    width, height = data["output"]["width"], data["output"]["height"]
    divisor = gcd(width, height)
    orientation = _orientation(width, height)
    formats = [{"id": format_id, "aspect_ratio": label(format_id), "width": spec["width"],
                "height": spec["height"], "orientation": _orientation(spec["width"], spec["height"])}
               for format_id, spec in ((main_format(data), data["output"]), *data["output"].get("formats", {}).items())]
    kinds = sorted({
        shot["kind"] for scene in data["scenes"] for shot in scene["shots"]
    })
    frames = sum(scene["duration_frames"] for scene in data["scenes"])
    needs_media = any(spec["required"] and spec["type"] in ASSET_TYPES
                      for spec in data["inputs"].values())
    path = path.resolve()
    return {
        "id": data["id"],
        "version": data["version"],
        "schema_version": data["schema_version"],
        "title": data["title"],
        "description": data["description"],
        "category": data["category"],
        "tags": data.get("tags", []),
        "engines": data["engines"],
        "shot_kinds": kinds,
        "duration_seconds": round(frames / data["output"]["fps"], 3),
        # True when only text inputs are required: renders with no media at all.
        "self_contained": not needs_media and kinds == ["motion_graphics"],
        "machine_checked_gates": [g["id"] for g in data["quality_gates"] if "check" in g],
        "output": {**data["output"], "orientation": orientation, "aspect_ratio": f"{width//divisor}:{height//divisor}"},
        # Every delivery format, main first; one job renders in any of them.
        "formats": formats,
        "required_inputs": {
            name: spec["type"] for name, spec in data["inputs"].items() if spec["required"]
        },
        "optional_inputs": {
            name: spec["type"] for name, spec in data["inputs"].items() if not spec["required"]
        },
        "style": data["style"],
        "has_human_gates": any(g["mode"] == "human" for g in data["quality_gates"]),
        "timeline": data.get("timeline"),
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
    }


def _orientation(width: int, height: int) -> str:
    return "portrait" if height > width else "landscape" if width > height else "square"


def discover(
    *, category: str | None = None, tag: str | None = None,
    orientation: str | None = None, engine: str | None = None,
    shot_kind: str | None = None, self_contained: bool | None = None,
    template_dirs: Iterable[Path] = (),
) -> list[dict]:
    results = []
    paths = [path for root in template_roots(template_dirs)
             for path in sorted(root.glob("**/blueprint.json"))]
    for path in paths:
        descriptor = describe_template(path)
        if category and descriptor["category"] != category:
            continue
        if tag and tag not in descriptor["tags"]:
            continue
        if orientation and orientation not in {f["orientation"] for f in descriptor["formats"]}:
            continue
        if engine and engine not in descriptor["engines"]:
            continue
        if shot_kind and shot_kind not in descriptor["shot_kinds"]:
            continue
        if self_contained is not None and descriptor["self_contained"] != self_contained:
            continue
        results.append(descriptor)
    return results


def inspect_template(identifier: str, template_dirs: Iterable[Path] = ()) -> dict:
    found = [entry for entry in discover(template_dirs=template_dirs) if entry["id"] == identifier]
    if len(found) != 1:
        raise ProductionError(f"Expected exactly one template named {identifier!r}, found {len(found)}")
    return found[0]


def scaffold(identifier: str, job_path: Path | None = None,
             template_dirs: Iterable[Path] = ()) -> dict:
    """Generate a *non-production-ready* job skeleton to fill and rights-clear.

    Only required inputs are listed; optional ones are reported by ``inspect``.
    No source assets are created, licensed, or invented by this function.
    """
    descriptor = inspect_template(identifier, template_dirs)
    template = read_json(ROOT / descriptor["path"])
    values = {}
    for name, spec in template["inputs"].items():
        if not spec["required"]:
            continue
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
        "template": template["id"],
        "template_version": template["version"],
        "inputs": values,
        "assets": {},
        "shot_assets": {},
        "approved_gates": []
    }
