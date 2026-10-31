"""Turn a locked blueprint and a content-only job into a deterministic render plan.

Never execute text provided in templates or manifests. Filesystem references in
jobs are confined to their directory; every asset must be rights-attested.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import textwrap
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from videogenome.blueprint import validate_blueprint
from videogenome.formats import apply_format, format_ids, label, main_format, normalise
from videogenome.layout import fit_copy, resolve_title_card
from videogenome.resources import DATA_ROOT, SCHEMAS, template_roots

ROOT = DATA_ROOT
JOB_SCHEMA = SCHEMAS / "job.schema.json"
TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9.-]+$")
TOKEN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
UNSAFE_TOKEN = re.compile(r"{{|}}")


class ProductionError(ValueError):
    """A job cannot be compiled without violating its blueprint contract."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    if "enum" in spec and value not in spec["enum"]:
        raise ProductionError(f"Input {name!r} must be one of {spec['enum']}")
    is_str = isinstance(value, str)
    if kind in ("string", "url") and not is_str:
        raise ProductionError(f"Input {name!r} must be a string")
    if kind == "string_array" and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        raise ProductionError(f"Input {name!r} must be a list of strings")
    if kind == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool)
                                 and (not isinstance(value, float) or math.isfinite(value))):
        raise ProductionError(f"Input {name!r} must be a finite number")
    if kind == "boolean" and not isinstance(value, bool):
        raise ProductionError(f"Input {name!r} must be boolean")
    expected = {"image": "image", "video": "video", "audio": "audio", "model_3d": "model_3d"}
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


def find_template(identifier: str, template_dirs: Iterable[Path] = ()) -> Path:
    """Resolve a template ID to exactly one blueprint inside a trusted root."""
    matches = []
    for root in template_roots(template_dirs):
        for path in sorted(root.glob("**/blueprint.json")):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("id") == identifier:
                    matches.append(path.resolve())
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
    if not matches:
        raise ProductionError(f"Unknown template {identifier!r}; run `videogenome catalog`")
    if len(set(matches)) > 1:
        raise ProductionError(f"Template id {identifier!r} is defined more than once: {matches}")
    return matches[0]


def resolve_template(reference: str, job_dir: Path, template_dirs: Iterable[Path] = ()) -> Path:
    """Accept a template ID, or a path to a blueprint inside a trusted root."""
    template_dirs = list(template_dirs)
    if TEMPLATE_ID.match(reference) and not reference.endswith(".json"):
        return find_template(reference, template_dirs)
    requested = Path(reference)
    # Templates are trusted, reviewed data; assets are confined to the job.
    # A job outside the repository may reference a reviewed template by path,
    # but never one outside the trusted template directories.
    path = (requested if requested.is_absolute() else job_dir / requested).resolve()
    trusted = [ROOT.resolve(), *template_roots(template_dirs)]
    if not path.is_file() or not any(path.is_relative_to(root) for root in trusted):
        raise ProductionError(
            "Template must be a catalog id or an existing blueprint inside a trusted "
            "template directory (see --templates / VIDEOGENOME_TEMPLATE_PATH)"
        )
    return path


def with_defaults(blueprint: dict, inputs: dict) -> dict:
    """Job inputs plus blueprint defaults for omitted optional inputs."""
    defaults = {name: spec["default"] for name, spec in blueprint["inputs"].items()
                if "default" in spec and name not in inputs}
    return {**defaults, **inputs}


def _compile_picture(blueprint: dict, segments: list[dict]) -> dict:
    timeline = blueprint.get("timeline", {})
    position = {segment["shot_id"]: index for index, segment in enumerate(segments)}
    transitions = []
    for transition in timeline.get("transitions", []):
        index = position[transition["after_shot"]]
        transitions.append({
            "from_shot": transition["after_shot"], "to_shot": segments[index + 1]["shot_id"],
            "cut_frame": segments[index]["end_frame"], "kind": transition["kind"],
            "duration_frames": transition["duration_frames"],
            "color": transition.get("color", "#000000"),
        })
    return {
        "transitions": sorted(transitions, key=lambda t: t["cut_frame"]),
        "fade_in_frames": timeline.get("fade_in_frames", 0),
        "fade_out_frames": timeline.get("fade_out_frames", 0),
    }


def _caption_cue(cue: dict, style: dict, inputs: dict, fps: int) -> dict:
    """One caption cue with its copy checked against the locked line and reading limits."""
    text = " ".join(_substitute(cue["text_template"], inputs).split())
    if not text or any(unicodedata.category(char) == "Cc" for char in text):
        raise ProductionError(f"Caption {cue['id']!r} needs nonempty printable text")
    if any(len(word) > style["max_chars_per_line"] for word in text.split()):
        raise ProductionError(f"Caption {cue['id']!r} contains a word too long for the line limit")
    lines = textwrap.wrap(text, width=style["max_chars_per_line"],
                          break_long_words=False, break_on_hyphens=False)
    if len(lines) > style["max_lines"]:
        raise ProductionError(f"Caption {cue['id']!r} exceeds the line limit; shorten the copy")
    cps = len(text) * fps / cue["duration_frames"]
    if cps > style["max_chars_per_second"]:
        raise ProductionError(f"Caption {cue['id']!r} exceeds the reading-speed limit ({cps:.1f} chars/s)")
    return {"id": cue["id"], "start_frame": cue["start_frame"],
            "end_frame": cue["start_frame"] + cue["duration_frames"], "text": text, "lines": lines}


def _card_copy(card: dict, shot: dict, inputs: dict, output: dict) -> dict:
    """Title-card copy wrapped at the largest locked size that fits."""
    direction = shot["direction"]
    # Empty title cards are allowed as color pauses, not invented copy.
    text = " ".join(_substitute(direction.get("text_template", ""), inputs).split())
    kicker = " ".join(_substitute(direction.get("kicker_template", ""), inputs).split())
    for label, copy in (("Text", text), ("Kicker", kicker)):
        if any(unicodedata.category(char) == "Cc" for char in copy):
            raise ProductionError(f"{label} for shot {shot['id']!r} contains control characters")
    try:
        size, lines = fit_copy(card, text, kicker, output)
    except ValueError as exc:
        raise ProductionError(f"Copy for shot {shot['id']!r} does not fit: {exc}") from exc
    return {"text": text, "lines": lines, "font_size": size, "kicker": kicker}


def copy_issues(blueprint: dict, inputs: dict) -> tuple[list[dict], list[dict]]:
    """Check every piece of on-screen copy the given text inputs feed.

    Unlike ``compile_job`` this reports all problems at once, each with the
    inputs it depends on, so a writer can revise exactly those slots. Items
    whose inputs are not all present yet are skipped. Returns ``(issues,
    cards)``: ``{"slots", "where", "problem"}`` entries and the compiled
    title-card copy (for a renderer's glyph-accurate check).
    """
    inputs = with_defaults(blueprint, inputs)
    card = resolve_title_card(blueprint)
    issues: list[dict] = []
    cards: list[dict] = []

    def ready(*templates: str) -> list[str] | None:
        slots = sorted({name for template in templates for name in TOKEN.findall(template)})
        return slots if all(name in inputs for name in slots) else None

    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            direction = shot["direction"]
            templates = (direction.get("text_template", ""), direction.get("kicker_template", ""))
            slots = ready(*templates)
            if not slots:
                continue
            try:
                if shot["kind"] == "motion_graphics":
                    cards.append({"shot_id": shot["id"], "slots": slots,
                                  **_card_copy(card, shot, inputs, blueprint["output"])})
                else:
                    _substitute(templates[0], inputs)
            except ProductionError as exc:
                issues.append({"slots": slots, "where": f"on-screen text of shot {shot['id']}",
                               "problem": str(exc)})
    captions = blueprint.get("timeline", {}).get("captions")
    if captions:
        for cue in captions["cues"]:
            slots = ready(cue["text_template"])
            if not slots:
                continue
            try:
                _caption_cue(cue, captions["style"], inputs, blueprint["output"]["fps"])
            except ProductionError as exc:
                issues.append({"slots": slots, "where": f"caption {cue['id']}", "problem": str(exc)})
    return issues, cards


def _compile_timeline(blueprint: dict, inputs: dict, assets: dict, skip: set[str] = frozenset()) -> dict:
    source = blueprint["timeline"]
    tracks = []
    for track in source.get("audio_tracks", []):
        if track["input_ref"] not in inputs and (track["input_ref"] in skip
                                                 or not blueprint["inputs"][track["input_ref"]]["required"]):
            continue  # An optional bed the job chose not to supply.
        asset_id = inputs.get(track["input_ref"])
        if not isinstance(asset_id, str) or assets.get(asset_id, {}).get("kind") != "audio":
            raise ProductionError(f"Audio track {track['id']!r} requires audio input {track['input_ref']!r}")
        tracks.append({
            "id": track["id"], "asset_id": asset_id,
            "start_frame": track["start_frame"], "duration_frames": track["duration_frames"],
            "in_frame": track.get("in_frame", 0), "gain_db": track.get("gain_db", 0),
            "fade_in_frames": track.get("fade_in_frames", 0),
            "fade_out_frames": track.get("fade_out_frames", 0),
        })
    timeline = {
        "source_audio": source.get("source_audio", "preserve"),
        "source_audio_gain_db": source.get("source_audio_gain_db", 0),
        "audio_tracks": tracks,
    }
    present = {track["id"]: track for track in tracks}
    ducking = []
    for duck in source.get("ducking", []):
        windows = [(present[o]["start_frame"], present[o]["start_frame"] + present[o]["duration_frames"])
                   for o in duck["under"] if o in present]
        if duck["track"] in present and windows:  # Optional tracks may be absent.
            ducking.append({"track": duck["track"], "windows": sorted(windows),
                            "depth_db": duck.get("depth_db", 10), "ramp_frames": duck.get("ramp_frames", 6)})
    if ducking:
        timeline["ducking"] = ducking
    if "captions" in source:
        style = source["captions"]["style"]
        cues = []
        for cue in sorted(source["captions"]["cues"], key=lambda c: c["start_frame"]):
            cues.append(_caption_cue(cue, style, inputs, blueprint["output"]["fps"]))
        timeline["captions"] = {"style": style, "cues": cues}
    return timeline


def job_format(job: dict, blueprint: dict, requested: str | None = None) -> str:
    """The format a job renders in: ``requested``, else the job's own, else the main one.

    Media a pipeline produced is made at one frame size, so a job holding produced
    media renders only in the format it was produced for.
    """
    own = normalise(job["format"]) if job.get("format") else main_format(blueprint)
    wanted = normalise(requested) if requested else own
    if wanted != own and any("generation" in asset for asset in job.get("assets", {}).values()):
        raise ProductionError(
            f"This job's media was produced for the {label(own)} format; produce it for "
            f"{label(wanted)} instead (`videogenome make --format {wanted}`)")
    if wanted not in format_ids(blueprint):
        apply_format(blueprint, wanted)  # Raises with the formats the template offers.
    return wanted


def compile_job(job_path: Path, *, template_dirs: Iterable[Path] = (),
                allow_pending: bool = False, format: str | None = None) -> dict[str, Any]:
    """Compile a job to a render plan.

    With ``allow_pending`` (used by ``validate``), producible inputs that have not
    been produced yet are listed in ``plan["pending_inputs"]`` instead of failing;
    such a plan is for checking only and is never rendered. ``format`` picks one of
    the template's delivery formats (default: the job's ``format``, else the main one).
    """
    job_path = job_path.resolve()
    job_dir = job_path.parent
    job = read_json(job_path)
    _validate_json(job, read_json(JOB_SCHEMA), "production job")

    template_path = resolve_template(job["template"], job_dir, template_dirs)
    source = read_json(template_path)
    blueprint_errors = validate_blueprint(source)
    if blueprint_errors:
        raise ProductionError("Invalid referenced blueprint: " + "; ".join(blueprint_errors))
    if source["version"] != job["template_version"]:
        raise ProductionError(
            f"Template version mismatch: job pins {job['template_version']}, "
            f"actual {source['version']}"
        )
    format_id = job_format(job, source, format)
    blueprint = apply_format(source, format_id)

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
            "rights": spec["rights"], "origin": spec["origin"],
            **({"generation": spec["generation"]} if "generation" in spec else {}),
        }

    inputs = with_defaults(blueprint, job.get("inputs", {}))
    unknown = sorted(set(inputs) - set(blueprint["inputs"]))
    if unknown:
        raise ProductionError(f"Undeclared inputs (template is locked): {unknown}")
    pending = [name for name, spec in blueprint["inputs"].items()
               if allow_pending and name not in inputs and "produce" in spec]
    for name, spec in blueprint["inputs"].items():
        if name not in inputs:
            if spec["required"] and name not in pending:
                hint = (f" (producible via {spec['produce']['capability']!r}: run `videogenome produce` "
                        "or `make` with a --pipeline that routes it)" if "produce" in spec else "")
                raise ProductionError(f"Missing required input: {name}{hint}")
            continue
        _check_input(name, spec, inputs[name], assets)

    all_ids: dict[str, dict] = {}
    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            all_ids[shot["id"]] = shot
    unknown_bindings = sorted(set(job.get("shot_assets", {})) - set(all_ids))
    if unknown_bindings:
        raise ProductionError(f"Unknown shot asset bindings: {unknown_bindings}")

    card = resolve_title_card(blueprint)
    background = card.get("background_input")
    if background and isinstance(inputs.get(background), str):
        card["background_asset"] = inputs[background]
    frame = 0
    segments: list[dict] = []
    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            kind = shot["kind"]
            binding = job.get("shot_assets", {}).get(shot["id"])
            required_kind = "image" if kind == "still_image" else "video"
            if binding is None and kind != "motion_graphics":
                # Bind from the shot's single declared media input, if unambiguous.
                candidates = [inputs[ref] for ref in shot.get("input_refs", [])
                              if blueprint["inputs"][ref]["type"] == required_kind
                              and isinstance(inputs.get(ref), str)]
                if len(candidates) == 1:
                    binding = {"asset": candidates[0]}
            waiting = [ref for ref in shot.get("input_refs", []) if ref in pending
                        and blueprint["inputs"][ref]["type"] == required_kind]
            if kind != "motion_graphics" and not binding and not waiting:
                raise ProductionError(
                    f"Shot {shot['id']!r} ({kind}) needs a rendered {required_kind} asset"
                )
            if binding and kind == "motion_graphics":
                raise ProductionError(f"Graphic shot {shot['id']!r} does not accept external shot media")
            asset_id = binding["asset"] if binding else None
            if asset_id is not None and (asset_id not in records or records[asset_id]["kind"] != required_kind):
                raise ProductionError(f"Shot {shot['id']!r} needs a {required_kind} asset")
            graphics = {}
            if kind == "motion_graphics":
                graphics = _card_copy(card, shot, inputs, blueprint["output"])
                text = graphics.pop("text")
            else:
                text = _substitute(shot["direction"].get("text_template", ""), inputs)
            duration = shot["duration_frames"]
            segment = {
                "scene_id": scene["id"], "shot_id": shot["id"], "kind": kind,
                "start_frame": frame, "end_frame": frame + duration,
                "duration_frames": duration, "text": text,
                "asset_id": asset_id,
                "in_seconds": binding.get("in_seconds", 0) if binding else 0,
                "fit": (binding or {}).get("fit", shot.get("fit", "contain")),
                **({"motion": shot["motion"]} if "motion" in shot else {}),
                **graphics,
            }
            segments.append(segment)
            frame += duration

    human_gate_ids = {g["id"] for g in blueprint["quality_gates"] if g["mode"] == "human"}
    approved = set(job.get("approved_gates", []))
    if unknown_approvals := (approved - human_gate_ids):
        raise ProductionError(f"Cannot approve unknown/non-human gates: {sorted(unknown_approvals)}")

    output = blueprint["output"]
    plan = {
        "ir_version": blueprint["schema_version"],
        "job_id": job["id"], "template_id": blueprint["id"],
        "template_version": blueprint["version"],
        "format": format_id,
        "template_sha256": sha256_file(template_path),
        "job_sha256": sha256_file(job_path),
        "output": output, "palette": blueprint["style"]["palette"],
        "title_card": card,
        "segments": segments, "total_frames": frame,
        "picture": _compile_picture(blueprint, segments),
        "assets": records,
        "quality_gates": [
            {
                **gate,
                "status": ("self_attested_approved" if gate["id"] in approved else "not_evaluated")
            }
            for gate in blueprint["quality_gates"]
        ],
    }
    if "timeline" in blueprint:
        plan["timeline"] = _compile_timeline(blueprint, inputs, records, skip=set(pending))
    if pending:
        plan["pending_inputs"] = pending
    return plan
