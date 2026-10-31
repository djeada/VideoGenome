"""Validate VideoGenome blueprints: JSON Schema + cross-field invariants.

This does not render media or execute declared QA gates.
"""
from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

from videogenome.formats import errors as format_errors, label, variants
from videogenome.resources import SCHEMAS

SCHEMA_PATH = SCHEMAS / "blueprint.schema.json"
SLOT = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
TEXT_INPUT_TYPES = ("string", "number", "url")


def _version(data: dict) -> tuple[int, ...]:
    return tuple(int(part) for part in data["schema_version"].split("."))


def _timeline_errors(data: dict) -> list[str]:
    timeline = data.get("timeline", {})
    total = sum(scene["duration_frames"] for scene in data["scenes"])
    errors = []
    for label, entries in (
        ("audio track", timeline.get("audio_tracks", [])),
        ("caption cue", timeline.get("captions", {}).get("cues", [])),
    ):
        ids = set()
        for entry in entries:
            if entry["id"] in ids:
                errors.append(f"duplicate {label} id: {entry['id']}")
            ids.add(entry["id"])
            if entry["start_frame"] + entry["duration_frames"] > total:
                errors.append(f"{label} {entry['id']}: extends beyond the picture timeline")
    for track in timeline.get("audio_tracks", []):
        spec = data["inputs"].get(track["input_ref"], {})
        if spec.get("type") != "audio":
            errors.append(f"audio track {track['id']}: input_ref must name an audio input")
        if track.get("fade_in_frames", 0) + track.get("fade_out_frames", 0) > track["duration_frames"]:
            errors.append(f"audio track {track['id']}: fades exceed track duration")
    captions = timeline.get("captions")
    if data["schema_version"] != "0.1.0" and data["output"]["captions"] and not captions:
        errors.append("captioned output requires timeline caption cues")
    if captions:
        if not data["output"]["captions"]:
            errors.append("timeline captions require output.captions=true")
        style = captions["style"]
        # Conservative full-em width, with room for the renderer's 8px box.
        if style["max_chars_per_line"] * style["font_size"] + 16 > data["output"]["width"] - 2 * style["margin_x"]:
            errors.append("caption line width exceeds the horizontal safe area")
        if style["max_lines"] * (style["font_size"] + 6) + style["margin_bottom"] + 8 > data["output"]["height"]:
            errors.append("caption block exceeds the vertical safe area")
        end = 0
        for cue in sorted(captions["cues"], key=lambda c: c["start_frame"]):
            if cue["start_frame"] < end:
                errors.append(f"caption cue {cue['id']}: overlaps another cue")
            end = max(end, cue["start_frame"] + cue["duration_frames"])
            for name in SLOT.findall(cue["text_template"]):
                if data["inputs"].get(name, {}).get("type") not in TEXT_INPUT_TYPES:
                    errors.append(f"caption cue {cue['id']}: invalid text input {name!r}")
    return errors


def _picture_errors(data: dict, shots: list[dict]) -> list[str]:
    """Transitions and program fades must fit inside the shots they touch."""
    timeline = data.get("timeline", {})
    errors = []
    index = {shot["id"]: position for position, shot in enumerate(shots)}
    # Frames consumed at the start (incoming) and end (outgoing) of each shot.
    head = [0] * len(shots)
    tail = [0] * len(shots)
    head[0] = timeline.get("fade_in_frames", 0)
    tail[-1] = timeline.get("fade_out_frames", 0)
    seen = set()
    for transition in timeline.get("transitions", []):
        name = transition["after_shot"]
        if name not in index:
            errors.append(f"transition after unknown shot {name!r}")
            continue
        if name in seen:
            errors.append(f"duplicate transition after shot {name!r}")
        seen.add(name)
        position = index[name]
        if position == len(shots) - 1:
            errors.append(f"transition after {name!r}: the final shot has no following shot")
            continue
        frames = transition["duration_frames"]
        if transition["kind"] == "crossfade":
            # The incoming shot's first frames blend over the outgoing shot's
            # handle, so the incoming shot must be longer than the overlap.
            head[position + 1] += frames
        else:
            tail[position] += (frames + 1) // 2
            head[position + 1] += frames // 2
    for position, shot in enumerate(shots):
        if head[position] + tail[position] > shot["duration_frames"] - 1:
            errors.append(f"shot {shot['id']}: transitions and fades leave no clean frames")
    return errors


def _title_card_errors(data: dict, shots: list[dict]) -> list[str]:
    card = data["style"].get("title_card")
    errors = []
    if not card:
        return errors
    palette = {color.upper() for color in data["style"]["palette"]}
    for key in ("background", "text_color", "accent_color"):
        if key in card and card[key].upper() not in palette:
            errors.append(f"title_card.{key} {card[key]} is not in the locked palette")
    if card.get("accent_bar") and "accent_color" not in card:
        errors.append("title_card.accent_bar requires accent_color")
    if card["min_font_size"] > card["font_size"]:
        errors.append("title_card.min_font_size exceeds font_size")
    width, height = data["output"]["width"], data["output"]["height"]
    if 2 * card.get("safe_margin_x", 0) >= width * 0.8:
        errors.append("title_card horizontal margins leave too little room for copy")
    vertical = card.get("safe_margin_top", 0) + card.get("safe_margin_bottom", 0)
    if vertical + card["min_font_size"] * 1.5 > height:
        errors.append("title_card vertical margins leave too little room for copy")
    graphic_lengths = [s["duration_frames"] for s in shots if s["kind"] == "motion_graphics"]
    if graphic_lengths and card.get("entrance_frames", 0) >= min(graphic_lengths):
        errors.append("title_card.entrance_frames must be shorter than every graphic shot")
    return errors


def _gate_errors(data: dict) -> list[str]:
    errors = []
    for gate in data["quality_gates"]:
        check = gate.get("check")
        if not check:
            continue
        if gate["mode"] != "automated":
            errors.append(f"gate {gate['id']}: only automated gates may declare a machine check")
        if "min" not in check and "max" not in check:
            errors.append(f"gate {gate['id']}: check needs min and/or max")
        if "min" in check and "max" in check and check["min"] > check["max"]:
            errors.append(f"gate {gate['id']}: check min exceeds max")
    return errors


MEDIA_INPUTS = {"audio": "audio", "image": "image", "video": "video"}
ASSET_INPUTS = {"image", "image_array", "video", "video_array", "audio", "model_3d"}


def _recipe_errors(label: str, request: dict, media: str, inputs: dict | None = None) -> list[str]:
    """A procedural request must name a catalog recipe, preset and params it accepts."""
    from videogenome.procedural import catalog
    recipe_id = request.get("recipe")
    if not isinstance(recipe_id, str) or SLOT.search(recipe_id):
        return [f"{label}: procedural request needs a literal recipe id"]
    try:
        recipe = catalog.get(recipe_id)
    except Exception as exc:  # noqa: BLE001 - unknown recipe or invalid catalog
        return [f"{label}: {exc}"]
    errors = []
    if media not in recipe.data["media"]:
        errors.append(f"{label}: recipe {recipe_id} cannot produce {media}")
    preset = request.get("preset")
    presets = recipe.data.get("presets", {})
    if isinstance(preset, str) and not SLOT.search(preset) and preset not in presets:
        errors.append(f"{label}: recipe {recipe_id} has no preset {preset!r}")
    whole = SLOT.fullmatch(preset.strip()) if isinstance(preset, str) else None
    if whole and inputs is not None:  # "{{look}}": every value the slot allows must be a real preset.
        spec = inputs.get(whole.group(1), {})
        choices = list(spec.get("enum", [])) + ([spec["default"]] if "default" in spec else [])
        missing = sorted({str(c) for c in choices} - set(presets))
        if missing:
            errors.append(f"{label}: recipe {recipe_id} has no preset(s) {missing} that input "
                          f"{whole.group(1)!r} can choose")
    unknown = set(request.get("params", {})) - set(recipe.data["params"]["properties"])
    if unknown:
        errors.append(f"{label}: recipe {recipe_id} has no params {sorted(unknown)}")
    return errors


def _produce_errors(data: dict) -> list[str]:
    """Producible inputs name a capability whose media matches the input type."""
    from videogenome.plugins import CAPABILITIES
    errors = []
    for name, spec in data["inputs"].items():
        produce = spec.get("produce")
        if not produce:
            continue
        label = f"input {name}"
        media = MEDIA_INPUTS.get(spec["type"])
        if media is None:
            errors.append(f"{label}: only audio, image or video inputs can be produced")
            continue
        contract = CAPABILITIES.get(produce["capability"])
        if contract:  # Plugin-defined capabilities are checked when produced.
            if media not in contract["media"]:
                errors.append(f"{label}: capability {produce['capability']} cannot produce {media}")
            unknown = set(produce.get("request", {})) - set(contract["fields"])
            if unknown:
                errors.append(f"{label}: request fields {sorted(unknown)} are not part of "
                              f"{produce['capability']}")
        for slot in SLOT.findall(json.dumps(produce.get("request", {}))):
            if data["inputs"].get(slot, {}).get("type") not in (*TEXT_INPUT_TYPES, "boolean"):
                errors.append(f"{label}: request slot {slot!r} must be a text, number or boolean input")
        if produce["capability"] == "procedural":
            errors.extend(_recipe_errors(label, produce.get("request", {}), media, data["inputs"]))
        for ref in produce.get("references", []):
            if data["inputs"].get(ref, {}).get("type") not in ASSET_INPUTS or ref == name:
                errors.append(f"{label}: reference {ref!r} must be another media input")
    return errors


def _v04_feature_errors(data: dict, shots: list[dict]) -> list[str]:
    """Card backgrounds, still motion, ducking and enumerated inputs."""
    errors = []
    card = data["style"].get("title_card", {})
    background = card.get("background_input")
    if background:
        spec = data["inputs"].get(background)
        if not spec or spec["type"] not in ("image", "video"):
            errors.append(f"title_card.background_input {background!r} must name an image or video input")
    for shot in shots:
        if "motion" in shot and shot["kind"] != "still_image":
            errors.append(f"shot {shot['id']}: motion applies to still_image shots only")
    tracks = {t["id"] for t in data.get("timeline", {}).get("audio_tracks", [])}
    for duck in data.get("timeline", {}).get("ducking", []):
        if duck["track"] not in tracks:
            errors.append(f"ducking: unknown track {duck['track']!r}")
        for other in duck["under"]:
            if other not in tracks or other == duck["track"]:
                errors.append(f"ducking {duck['track']}: 'under' must name other audio tracks ({other!r})")
    for name, spec in data["inputs"].items():
        if "enum" in spec and spec["type"] not in ("string", "number"):
            errors.append(f"input {name}: enum is only valid for string or number inputs")
        if "default" in spec:
            if spec["required"]:
                errors.append(f"input {name}: only optional inputs may declare a default")
            if "enum" in spec and spec["default"] not in spec["enum"]:
                errors.append(f"input {name}: default is not one of its enum values")
    return errors


FILLABLE_TYPES = ("string", "string_array", "number", "boolean", "url")


def _fill_errors(data: dict) -> list[str]:
    errors = []
    for name, spec in data["inputs"].items():
        if "fill" in spec and spec["type"] not in FILLABLE_TYPES:
            errors.append(f"input {name}: fill applies to text, number or boolean inputs only")
        if spec.get("fill") == "verbatim" and spec["type"] not in ("string", "string_array", "number"):
            errors.append(f"input {name}: verbatim fill applies to string and number inputs only")
        if spec.get("whole_quote") and (spec.get("fill") != "verbatim" or spec["type"] != "string"):
            errors.append(f"input {name}: whole_quote applies to verbatim string inputs only")
        partner = spec.get("grounded_with")
        if partner is not None:
            other = data["inputs"].get(partner, {})
            if spec.get("fill") != "verbatim" or other.get("fill") != "verbatim" or partner == name:
                errors.append(f"input {name}: grounded_with must name another verbatim input, and both must be verbatim")
    return errors


def _version_errors(data: dict, shots: list[dict]) -> list[str]:
    """Features introduced in newer schemas must not leak into older contracts."""
    errors = []
    if _version(data) < (0, 6, 0) and "formats" in data["output"]:
        errors.append("output.formats requires schema_version 0.6.0")
    if _version(data) < (0, 5, 0):
        newer = [name for name, spec in data["inputs"].items() if "fill" in spec or "grounded_with" in spec or "whole_quote" in spec]
        if newer:
            errors.append(f"inputs {newer} use fill, which requires schema_version 0.5.0")
        if "copy_examples" in data:
            errors.append("copy_examples requires schema_version 0.5.0")
    if _version(data) < (0, 4, 0):
        newer = [name for name, spec in data["inputs"].items()
                 if "produce" in spec or spec["type"] == "model_3d" or "enum" in spec or "default" in spec]
        if newer:
            errors.append(f"inputs {newer} use produce/model_3d/enum/default, which requires schema_version 0.4.0")
        card = data["style"].get("title_card", {})
        if ("background_input" in card or "background_dim" in card
                or any("motion" in s or "fit" in s for s in shots)
                or "ducking" in data.get("timeline", {})):
            errors.append("title_card background / shot motion / ducking requires schema_version 0.4.0")
    if _version(data) >= (0, 3, 0):
        return errors
    used = []
    if "title_card" in data["style"]:
        used.append("style.title_card")
    if "loudness" in data["output"] or "poster_frame" in data["output"]:
        used.append("output.loudness/poster_frame")
    timeline = data.get("timeline", {})
    if any(k in timeline for k in ("transitions", "fade_in_frames", "fade_out_frames")):
        used.append("timeline transitions/fades")
    if any("kicker_template" in shot["direction"] for shot in shots):
        used.append("direction.kicker_template")
    if any("check" in gate for gate in data["quality_gates"]):
        used.append("quality_gates[].check")
    return errors + [f"{feature} requires schema_version 0.3.0" for feature in used]


_SCHEMA_CACHE: dict[tuple[float, int], tuple[dict, Draft202012Validator]] = {}


def _cached_validator() -> tuple[dict, Draft202012Validator]:
    """Check the schema against the meta-schema once per file version, not once per blueprint."""
    stat = SCHEMA_PATH.stat()
    key = (stat.st_mtime, stat.st_size)
    if key not in _SCHEMA_CACHE:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _SCHEMA_CACHE.clear()
        _SCHEMA_CACHE[key] = (schema, Draft202012Validator(schema))
    return _SCHEMA_CACHE[key]


def load_schema() -> dict:
    return _cached_validator()[0]


def validate_blueprint(data: object, schema: dict | None = None) -> list[str]:
    """Return portable, human-readable validation errors."""
    validator = Draft202012Validator(schema) if schema is not None else _cached_validator()[1]
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
    shots: list[dict] = []
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
            shots.append(shot)
            shot_id = shot["id"]
            if shot_id in shot_ids:
                errors.append(f"duplicate shot id: {shot_id}")
            shot_ids.add(shot_id)
            for ref in shot.get("input_refs", []):
                if ref not in inputs:
                    errors.append(f"shot {shot_id}: unknown input_ref {ref!r}")
            kicker = shot["direction"].get("kicker_template")
            if kicker is not None:
                if shot["kind"] != "motion_graphics":
                    errors.append(f"shot {shot_id}: kicker_template is only valid on motion_graphics")
                for name in SLOT.findall(kicker):
                    if data["inputs"].get(name, {}).get("type") not in TEXT_INPUT_TYPES:
                        errors.append(f"shot {shot_id}: invalid kicker input {name!r}")
    for gate in data["quality_gates"]:
        if gate["id"] in gate_ids:
            errors.append(f"duplicate quality gate id: {gate['id']}")
        gate_ids.add(gate["id"])
    total = sum(scene["duration_frames"] for scene in data["scenes"])
    if data["output"].get("poster_frame", 0) >= total:
        errors.append("output.poster_frame lies beyond the programme")
    errors.extend(_version_errors(data, shots))
    errors.extend(_timeline_errors(data))
    errors.extend(_picture_errors(data, shots))
    errors.extend(_title_card_errors(data, shots))
    errors.extend(_gate_errors(data))
    errors.extend(_produce_errors(data))
    errors.extend(_v04_feature_errors(data, shots))
    errors.extend(_fill_errors(data))
    errors.extend(format_errors(data))
    if not errors and "copy_examples" in data:
        from videogenome.fill import example_errors  # Late: fill depends on the compiler.
        errors.extend(example_errors(data))
    if not errors and data["output"].get("formats"):
        # Each format must stand on its own: caption safe areas, title-card fit and
        # copy examples are checked again at that frame size.
        for format_id, variant in variants(data)[1:]:
            errors.extend(f"format {label(format_id)}: {problem}" for problem in validate_blueprint(variant))
    return errors
