"""Turn a locked blueprint and a content-only job into a deterministic render plan.

Never execute text provided in templates or manifests. Filesystem references in
jobs are confined to their directory; every asset must be rights-attested.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.validate import validate_blueprint

ROOT = Path(__file__).resolve().parents[1]
JOB_SCHEMA = ROOT / "schemas" / "job.schema.json"
TOKEN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
UNSAFE_TOKEN = re.compile(r"{{|}}")


class ProductionError(ValueError):
    """A job cannot be compiled without violating its blueprint contract."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProductionError(f"Expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confined_file(root: Path, relative: str) -> Path:
    """Refuse absolute paths, ../ escapes, symlinks outside the job, and URLs."""
    value = Path(relative)
    if value.is_absolute() or "://" in relative:
        raise ProductionError(f"Only local, relative asset paths are accepted: {relative!r}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ProductionError(f"Asset escapes job directory: {relative!r}")
    if not resolved.is_file():
        raise ProductionError(f"Missing asset file: {relative!r}")
    return resolved


def _validate_json(document: dict, schema: dict, label: str) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: str(list(error.absolute_path)))
    if errors:
        details = "; ".join(
            f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors[:12]
        )
        raise ProductionError(f"Invalid {label}: {details}")


def _check_input(name: str, spec: dict, value: Any, assets: dict) -> None:
    kind = spec["type"]
    is_str = isinstance(value, str)
    if kind in ("string", "url") and not is_str:
        raise ProductionError(f"Input {name!r} must be a string")
    if kind == "string_array" and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        raise ProductionError(f"Input {name!r} must be a list of strings")
    if kind == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool)):
        raise ProductionError(f"Input {name!r} must be numeric")
    if kind == "boolean" and not isinstance(value, bool):
        raise ProductionError(f"Input {name!r} must be boolean")
    expected = {"image": "image", "video": "video", "audio": "audio"}
    if kind in expected:
        if not is_str or value not in assets or assets[value]["kind"] != expected[kind]:
            raise ProductionError(f"Input {name!r} must reference a declared {expected[kind]} asset")
    arrays = {"image_array": "image", "video_array": "video"}
    if kind in arrays:
        if not isinstance(value, list) or not value or any(
            not isinstance(x, str) or x not in assets or assets[x]["kind"] != arrays[kind] for x in value
        ):
            raise ProductionError(f"Input {name!r} must reference a nonempty list of {arrays[kind]} assets")


def _substitute(template: str, inputs: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in inputs:
            raise ProductionError(f"Unbound text slot: {name}")
        value = inputs[name]
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ProductionError(f"Text slot {name!r} must have a scalar value")
        return str(value)

    result = TOKEN.sub(replace, template)
    if UNSAFE_TOKEN.search(result):
        raise ProductionError("Invalid or nested text slot; only {{input_name}} is supported")
    if len(result) > 300:
        raise ProductionError("Rendered text exceeds 300 characters; shorten the copy")
    return result


def compile_job(job_path: Path) -> dict[str, Any]:
    job_path = job_path.resolve()
    job_dir = job_path.parent
    job = read_json(job_path)
    _validate_json(job, read_json(JOB_SCHEMA), "production job")

    # Templates are trusted repository code/data; assets are confined to the job.
    # Allow a job outside the repository to reference a reviewed template by
    # absolute path, but reject templates outside the trusted repository root.
    requested_template = Path(job["template"])
    template_path = (
        requested_template if requested_template.is_absolute()
        else job_dir / requested_template
    ).resolve()
    if not template_path.is_relative_to(ROOT.resolve()) or not template_path.is_file():
        raise ProductionError("Template must be an existing file inside the VideoGenome repository")
    blueprint = read_json(template_path)
    blueprint_errors = validate_blueprint(blueprint)
    if blueprint_errors:
        raise ProductionError("Invalid referenced blueprint: " + "; ".join(blueprint_errors))
    if blueprint["version"] != job["template_version"]:
        raise ProductionError(
            f"Template version mismatch: job pins {job['template_version']}, "
            f"actual {blueprint['version']}"
        )

    assets = job.get("assets", {})
    records: dict[str, dict] = {}
    for asset_id, spec in assets.items():
        if not spec["rights"]["cleared"]:
            raise ProductionError(f"Asset {asset_id!r} is not rights-cleared (self-attested)")
        if not spec["rights"]["evidence"]:
            raise ProductionError(f"Asset {asset_id!r} requires rights evidence/reference")
        source = confined_file(job_dir, spec["path"])
        records[asset_id] = {
            "path": spec["path"], "kind": spec["kind"], "sha256": sha256_file(source),
            "rights": spec["rights"], "origin": spec["origin"]
        }

    inputs = job.get("inputs", {})
    unknown = sorted(set(inputs) - set(blueprint["inputs"]))
    if unknown:
        raise ProductionError(f"Undeclared inputs (template is locked): {unknown}")
    for name, spec in blueprint["inputs"].items():
        if name not in inputs:
            if spec["required"]:
                raise ProductionError(f"Missing required input: {name}")
            continue
        _check_input(name, spec, inputs[name], assets)

    all_ids: dict[str, dict] = {}
    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            all_ids[shot["id"]] = shot
    unknown_bindings = sorted(set(job.get("shot_assets", {})) - set(all_ids))
    if unknown_bindings:
        raise ProductionError(f"Unknown shot asset bindings: {unknown_bindings}")

    frame = 0
    segments: list[dict] = []
    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            kind = shot["kind"]
            binding = job.get("shot_assets", {}).get(shot["id"])
            required_kind = "image" if kind == "still_image" else "video"
            if kind != "motion_graphics" and not binding:
                raise ProductionError(
                    f"Shot {shot['id']!r} ({kind}) needs a rendered {required_kind} asset"
                )
            if binding and kind == "motion_graphics":
                raise ProductionError(f"Graphic shot {shot['id']!r} does not accept external shot media")
            asset_id = binding["asset"] if binding else None
            if asset_id is not None and (asset_id not in records or records[asset_id]["kind"] != required_kind):
                raise ProductionError(f"Shot {shot['id']!r} needs a {required_kind} asset")
            direction = shot["direction"]
            text = _substitute(direction.get("text_template", ""), inputs)
            if kind == "motion_graphics" and not text:
                # Empty title cards are allowed as color pauses, not invented copy.
                text = ""
            duration = shot["duration_frames"]
            segment = {
                "scene_id": scene["id"], "shot_id": shot["id"], "kind": kind,
                "start_frame": frame, "end_frame": frame + duration,
                "duration_frames": duration, "text": text,
                "asset_id": asset_id,
                "in_seconds": binding.get("in_seconds", 0) if binding else 0,
                "fit": binding.get("fit", "contain") if binding else "contain"
            }
            segments.append(segment)
            frame += duration

    human_gate_ids = {g["id"] for g in blueprint["quality_gates"] if g["mode"] == "human"}
    approved = set(job.get("approved_gates", []))
    if unknown_approvals := (approved - human_gate_ids):
        raise ProductionError(f"Cannot approve unknown/non-human gates: {sorted(unknown_approvals)}")

    output = blueprint["output"]
    return {
        "ir_version": "0.1.0",
        "job_id": job["id"], "template_id": blueprint["id"],
        "template_version": blueprint["version"],
        "template_sha256": sha256_file(template_path),
        "job_sha256": sha256_file(job_path),
        "output": output, "palette": blueprint["style"]["palette"],
        "segments": segments, "total_frames": frame,
        "assets": records,
        "quality_gates": [
            {
                **gate,
                "status": ("self_attested_approved" if gate["id"] in approved else "not_evaluated")
            }
            for gate in blueprint["quality_gates"]
        ],
    }
