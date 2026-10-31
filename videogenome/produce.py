"""Fill a job's producible inputs through the pipeline profile's providers.

A blueprint marks an input as producible:

    "narration": {"type": "audio", "required": true, "description": "...",
                  "produce": {"capability": "speech", "voice": "narrator",
                              "request": {"text": "{{script}}"}}}

If the job supplies the input (a real recording, licensed footage), it is
used as is. Otherwise ``produce`` builds a typed request from the job's text
slots, routes it to the profile's providers (a single provider, a fallback list
or a chain), conforms the result to the locked timing, records provenance, and
writes ``<job>.produced.json`` beside the job.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable

from videogenome.compiler import (
    ProductionError, confined_file, job_format, read_json, resolve_template, sha256_file, with_defaults,
)
from videogenome.formats import apply_format, job_stem, main_format
from videogenome.plugins import CAPABILITIES, Generated, PluginError, check_request
from videogenome.profile import Profile

SLOT = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
MEDIA_OF_INPUT = {"audio": "audio", "image": "image", "video": "video"}
PLACEHOLDER_RIGHTS = {"license": "MIT", "evidence": "Procedurally generated placeholder by "
                      "VideoGenome's placeholder provider; contains no third-party material."}
MANIFEST = "manifest.json"


class CopyTooLong(ProductionError):
    """Generated speech overruns its locked slot: the copy, not the provider, must change."""

    def __init__(self, input_name: str, seconds: float, need: float) -> None:
        super().__init__(f"input {input_name!r}: generated speech runs {seconds:.2f}s but the locked "
                         f"slot is {need:.2f}s; shorten the text")
        self.input = input_name
        self.seconds = seconds
        self.need = need


def _fill_text(template: str, inputs: dict, label: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = inputs.get(name)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ProductionError(f"{label} needs text input {name!r}")
        return str(value)
    # Verbatim: code, poetry and scripts depend on line breaks and indentation.
    text = SLOT.sub(replace, template).strip("\n")
    if "{{" in text or "}}" in text:
        raise ProductionError(f"{label}: nested or malformed slot")
    if len(text) > 4000:
        raise ProductionError(f"{label}: request text exceeds 4000 characters")
    return text


def _fill_value(value, inputs: dict, label: str):
    """Templates inside request values; ``"{{slot}}"`` alone keeps the input's JSON type."""
    if isinstance(value, dict):
        # A param that is exactly "{{slot}}" for an input left out is omitted, so the recipe default applies.
        return {key: _fill_value(item, inputs, label) for key, item in value.items()
                if not (isinstance(item, str) and (whole := SLOT.fullmatch(item.strip()))
                        and whole.group(1) not in inputs)}
    if isinstance(value, list):
        # A whole-slot item whose (optional) input was left out is dropped, so a template can
        # map value_1..value_6 onto a recipe array and supply only as many as the brief has.
        return [_fill_value(item, inputs, label) for item in value
                if not (isinstance(item, str) and (whole := SLOT.fullmatch(item.strip()))
                        and whole.group(1) not in inputs)]
    if isinstance(value, str):
        whole = SLOT.fullmatch(value.strip())
        if whole and whole.group(1) in inputs and not isinstance(inputs[whole.group(1)], bool):
            return inputs[whole.group(1)]
        return _fill_text(value, inputs, label)
    return value


def timing_needs(blueprint: dict, name: str) -> float | None:
    """Seconds the locked timeline needs from this input, if it is timed."""
    fps = blueprint["output"]["fps"]
    timeline = blueprint.get("timeline", {})
    needs = [(t.get("in_frame", 0) + t["duration_frames"]) / fps
             for t in timeline.get("audio_tracks", []) if t["input_ref"] == name]
    crossfades = {t["after_shot"]: t["duration_frames"] for t in timeline.get("transitions", [])
                  if t["kind"] == "crossfade"}
    for scene in blueprint["scenes"]:
        for shot in scene["shots"]:
            if name in shot.get("input_refs", []) and shot["kind"] not in ("motion_graphics", "still_image"):
                needs.append((shot["duration_frames"] + crossfades.get(shot["id"], 0)) / fps)
    if blueprint["style"].get("title_card", {}).get("background_input") == name:
        needs.append(sum(scene["duration_frames"] for scene in blueprint["scenes"]) / fps)
    return max(needs) if needs else None


def _probe(path: Path) -> dict:
    from videogenome.render import probe
    return probe(path)


def _duration(metadata: dict, kind: str) -> float:
    for stream in metadata.get("streams", []):
        if stream.get("codec_type") == kind and stream.get("duration"):
            return float(stream["duration"])
    return float(metadata.get("format", {}).get("duration", 0) or 0)


def _conform(path: Path, media: str, capability: str, need: float | None, fps: int,
             workdir: Path, name: str) -> tuple[Path, dict]:
    label = f"input {name!r}"
    metadata = _probe(path)
    kinds = {s.get("codec_type") for s in metadata.get("streams", [])}
    if media == "audio" and "audio" not in kinds:
        raise PluginError(f"{label}: provider returned no audio stream")
    if media in ("image", "video") and "video" not in kinds:
        raise PluginError(f"{label}: provider returned no picture")
    facts: dict = {}
    if media == "audio":
        seconds = _duration(metadata, "audio")
        facts["raw_seconds"] = round(seconds, 3)
        if need is None:
            return path, facts
        if capability in ("speech", "voice_conversion"):
            if seconds > need + 1 / fps:
                raise CopyTooLong(name, seconds, need)
            conformed = workdir / "conformed.wav"
            samples = round(need * 48000)
            # Pad speech with silence to the locked slot so timing checks hold.
            completed = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                 "-af", f"aresample=48000,apad,atrim=end_sample={samples}", "-ac", "2",
                 "-c:a", "pcm_s16le", str(conformed)], capture_output=True, text=True, check=False)
            if completed.returncode:
                raise PluginError(f"{label}: cannot conform audio: {completed.stderr[-400:]}")
            facts["conformed_to_seconds"] = round(need, 3)
            return conformed, facts
        if seconds + 0.05 < need:
            raise PluginError(f"{label}: generated audio runs {seconds:.2f}s; the timeline needs {need:.2f}s")
        return path, facts
    if media == "video":
        seconds = _duration(metadata, "video")
        facts["raw_seconds"] = round(seconds, 3)
        if need is not None and seconds + 1 / fps < need:
            raise PluginError(f"{label}: generated clip runs {seconds:.2f}s; the shot needs {need:.2f}s")
    return path, facts


def _request(blueprint: dict, job: dict, name: str, spec: dict, profile: Profile | None,
             assets: dict, job_dir: Path) -> dict:
    """The typed request for one producible input (``profile`` None: roles pass through unmapped)."""
    produce = spec["produce"]
    capability = produce["capability"]
    if capability not in CAPABILITIES:
        raise ProductionError(f"Input {name!r}: unknown capability {capability!r}")
    contract = CAPABILITIES[capability]
    fields = contract["fields"]
    label = f"input {name!r}"
    request: dict = {"media": MEDIA_OF_INPUT[spec["type"]]}
    slots = with_defaults(blueprint, job.get("inputs", {}))
    for key, value in produce.get("request", {}).items():
        request[key] = _fill_value(value, slots, label)
    for role_field, table in (("voice", "voices"), ("style", "styles")):
        if role_field in produce and role_field in fields:
            value = profile.role(table, produce[role_field]) if profile is not None else None
            if value is None and role_field == "style":
                value = produce[role_field]  # Unmapped style roles pass through (e.g. a recipe preset).
            if value is not None:
                request[role_field] = value
    output = blueprint["output"]
    need = timing_needs(blueprint, name)
    automatic = {"fps": output["fps"]}
    if request["media"] != "audio":  # Sound does not depend on the frame: one take serves every format.
        automatic.update(width=output["width"], height=output["height"])
    if need is not None:
        automatic["duration_seconds" if capability not in ("speech",) else "max_seconds"] = round(need, 3)
    elif request["media"] == "video":
        automatic["duration_seconds"] = 3.0
    automatic["seed"] = int(hashlib.sha256(f"{job['id']}/{name}".encode()).hexdigest()[:8], 16) % 2**31
    for key, value in automatic.items():
        if key in fields and key not in request:
            request[key] = value
    references = {}
    for ref in produce.get("references", []):
        asset_id = job.get("inputs", {}).get(ref)
        if not isinstance(asset_id, str) or asset_id not in assets:
            raise ProductionError(f"{label} needs reference input {ref!r} to be supplied first")
        references[ref] = str(confined_file(job_dir, assets[asset_id]["path"]))
    if references:
        request["references"] = references
    check_request(capability, request)
    return request


def _preflight_rights(providers: list) -> None:
    """Refuse before spending compute if a provider cannot vouch for its output."""
    from videogenome.providers.placeholder import PlaceholderProvider
    for provider in providers:
        if isinstance(provider, PlaceholderProvider) or provider.reports_rights:
            continue
        if not provider.config.get("output_rights"):
            raise PluginError(
                f"Provider {provider.name!r} declares no output_rights; the operator must state the "
                "licence of its output (model/voice terms) in the pipeline profile")


def _rights(chain: list, steps: list[dict]) -> tuple[dict, bool, str]:
    """Combine each step's rights: reported per item, else the operator's attestation."""
    from videogenome.providers.placeholder import PlaceholderProvider
    licenses, evidence, origins = [], [], []
    placeholder = False
    for (provider, _), step in zip(chain, steps):
        if isinstance(provider, PlaceholderProvider):
            placeholder = True
            rights = PLACEHOLDER_RIGHTS
            origins.append("rendered")
        else:
            rights = step["metadata"].get("rights") or provider.config.get("output_rights")
            if not rights:
                raise PluginError(f"Provider {provider.name!r} returned media without rights information")
            origins.append(step["metadata"].get("origin_type", "generated"))
        licenses.append(rights["license"])
        evidence.append(f"{provider.name}: {rights['evidence']}")
    origin = "generated" if "generated" in origins else origins[-1]
    return ({"license": " + ".join(dict.fromkeys(licenses)), "evidence": " | ".join(evidence)},
            placeholder, origin)


def _recipe_hashes(chain: list, request: dict) -> dict[str, str]:
    """Code hashes of every recipe the request or a provider default names: editing a
    recipe's code must invalidate media made by its previous version."""
    names = {request.get("recipe")} if isinstance(request.get("recipe"), str) else set()
    for provider, _ in chain:
        for default in (provider.config.get("defaults") or {}).values():
            if isinstance(default, dict) and isinstance(default.get("recipe"), str):
                names.add(default["recipe"])
    if not names:
        return {}
    from videogenome.procedural import catalog
    hashes = {}
    for name in sorted(names):
        try:
            hashes[name] = catalog.get(name).sha256()
        except ProductionError:
            hashes[name] = "unknown"
    return hashes


def _cache_key(chain: list, request: dict) -> str:
    material = {"request": request, "recipes": _recipe_hashes(chain, request), "chain": [
        {"name": p.name, "type": type(p).__name__, "capability": c, "config": p.config}
        for p, c in chain]}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


def _run_chain(chain: list, request: dict, workdir: Path) -> tuple[Generated, list[dict]]:
    steps = []
    current: Generated | None = None
    for index, (provider, capability) in enumerate(chain):
        if capability not in provider.serves():
            raise PluginError(f"Provider {provider.name!r} is not configured for {capability!r}")
        contract = CAPABILITIES.get(capability)
        if contract is None:
            raise PluginError(f"Unknown capability {capability!r} in route")
        if index == 0:
            step_request = dict(request)
        else:  # Later steps transform the previous result.
            step_request = {k: v for k, v in request.items() if k in contract["fields"] or k == "media"}
            step_request["references"] = {**request.get("references", {}), "source": str(current.path)}
        margin = provider.config.get("duration_margin_seconds", 0)
        if margin and "duration_seconds" in step_request:
            step_request["duration_seconds"] = round(step_request["duration_seconds"] + margin, 3)
        check_request(capability, step_request)
        step_dir = workdir / f"step{index}"
        step_dir.mkdir()
        started = time.monotonic()
        current = provider.generate(capability, step_request, step_dir)
        if not current.path.is_file():
            raise PluginError(f"Provider {provider.name!r} reported {current.path} but it does not exist")
        steps.append({"provider": provider.name, "type": type(provider).__name__,
                      "capability": capability, "model": provider.config.get("model", {}),
                      "seconds_elapsed": round(time.monotonic() - started, 2),
                      "output_sha256": sha256_file(current.path), "metadata": current.metadata})
    assert current is not None
    return current, steps


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def produced_path(job_path: Path, format_id: str | None = None) -> Path:
    """``job.json`` -> ``job.produced.json`` (main format) or ``job.9x16.produced.json``."""
    stem = job_stem(job_path)
    return job_path.with_name(f"{stem}.{format_id}.produced.json" if format_id else f"{stem}.produced.json")


def produce(job_path: Path, profile: Profile, *, template_dirs: Iterable[Path] = (),
            force: bool = False, only: Iterable[str] = (), format: str | None = None) -> tuple[Path, list[dict]]:
    """Produce missing inputs for one delivery format (default: the job's, else the main one).

    Media for the main format goes to ``generated/``; another format's media goes to
    ``generated/<format>/``. Media that does not depend on the frame (music, sound
    effects, narration) is reused from any format that already made it.
    """
    job_path = job_path.resolve()
    job_dir = job_path.parent
    job = read_json(job_path)
    source = read_json(resolve_template(job["template"], job_dir, template_dirs))
    format_id = job_format(job, source, format)
    blueprint = apply_format(source, format_id)
    is_main = format_id == main_format(source)
    if is_main:
        job.pop("format", None)
    else:
        job["format"] = format_id
    job.setdefault("inputs", {})
    assets = job.setdefault("assets", {})
    generated_dir = job_dir / "generated" if is_main else job_dir / "generated" / format_id
    manifest_path = generated_dir / MANIFEST
    manifest = _read_manifest(manifest_path) if manifest_path.is_file() else {}
    shared = [_read_manifest(path) for path in sorted({job_dir / "generated" / MANIFEST,
                                                        *(job_dir / "generated").glob(f"*/{MANIFEST}")})
              if path != manifest_path and path.is_file()]
    only = set(only)
    report = []
    pending = [(name, spec) for name, spec in blueprint["inputs"].items()
               if "produce" in spec and name not in job["inputs"] and (not only or name in only)]
    while pending:
        progressed = False
        for name, spec in list(pending):
            refs = spec["produce"].get("references", [])
            if any(ref in dict(pending) for ref in refs):
                continue  # Produce what this one depends on first.
            pending.remove((name, spec))
            progressed = True
            entry = _produce_one(blueprint, job, name, spec, profile, assets, job_dir,
                                 generated_dir, manifest, force, shared)
            report.append(entry)
            if entry["status"] in ("generated", "reused"):  # Persist progress: a later failure keeps this.
                generated_dir.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if not progressed:
            raise ProductionError(f"Producible inputs reference each other: {[n for n, _ in pending]}")
    produced = produced_path(job_path, None if is_main else format_id)
    produced.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return produced, report


def _cached(entry: dict | None, key: str, job_dir: Path) -> bool:
    return bool(entry and entry.get("cache_key") == key and (job_dir / entry["path"]).is_file()
                and sha256_file(job_dir / entry["path"]) == entry["sha256"])


def _produce_one(blueprint, job, name, spec, profile, assets, job_dir, generated_dir,
                 manifest, force, shared=()) -> dict:
    capability = spec["produce"]["capability"]
    alternatives = profile.routes_for(capability)
    if not alternatives:
        if spec["required"]:
            raise ProductionError(
                f"Input {name!r} must be supplied or produced, but pipeline {profile.id!r} "
                f"routes no {capability!r} provider")
        return {"input": name, "capability": capability, "status": "skipped",
                "reason": f"optional; pipeline routes no {capability!r} provider"}
    request = _request(blueprint, job, name, spec, profile, assets, job_dir)
    failures = []
    for alternative in alternatives:
        chain = [(profile.provider(provider_name), step) for provider_name, step in alternative]
        key = _cache_key(chain, request)
        cached = manifest.get(name)
        if not force and _cached(cached, key, job_dir):
            _bind(job, assets, name, spec, cached["asset"])
            return {"input": name, "capability": capability, "status": "cached",
                    "path": cached["path"], "providers": [p.name for p, _ in chain]}
        # The same request made for another format (frame-independent media such as
        # music) is the same media: point at it rather than generating it again.
        other = next((m[name] for m in shared if _cached(m.get(name), key, job_dir)), None)
        if not force and other:
            manifest[name] = other
            _bind(job, assets, name, spec, other["asset"])
            return {"input": name, "capability": capability, "status": "reused",
                    "path": other["path"], "providers": [p.name for p, _ in chain]}
        try:
            _preflight_rights([p for p, _ in chain])
            with tempfile.TemporaryDirectory(prefix="videogenome-produce-") as directory:
                workdir = Path(directory)
                result, steps = _run_chain(chain, request, workdir)
                rights, placeholder, origin_type = _rights(chain, steps)
                final, facts = _conform(result.path, request["media"], capability,
                                        timing_needs(blueprint, name), blueprint["output"]["fps"],
                                        workdir, name)
                generated_dir.mkdir(parents=True, exist_ok=True)
                destination = generated_dir / f"{name}{final.suffix.lower() or '.bin'}"
                shutil.copyfile(final, destination)
        except PluginError as exc:
            failures.append(f"{' -> '.join(p.name for p, _ in chain)}: {exc}")
            continue
        relative = destination.relative_to(job_dir).as_posix()
        names = " -> ".join(f"{p.name} ({(p.config.get('model') or {}).get('name', type(p).__name__)})"
                            for p, _ in chain)
        attribution = [s["metadata"]["attribution"] for s in steps if s["metadata"].get("attribution")]
        recipes = [s["metadata"]["recipe"]["id"] for s in steps if s["metadata"].get("recipe")]
        if placeholder:
            description = f"Placeholder {capability} for input {name!r} by {names}"
        elif attribution:
            source = attribution[-1]
            description = (f"{source.get('title')!s} by {source.get('creator') or 'unknown creator'} "
                           f"({source.get('landing_page')}), retrieved by {names}")
        elif recipes:
            description = f"Procedural {request['media']} from recipe {recipes[-1]} for input {name!r}"
        else:
            description = f"Generated {capability} for input {name!r} by {names}"
        asset = {
            "kind": request["media"], "path": relative,
            "origin": {"type": "rendered" if placeholder else origin_type, "description": description[:500]},
            "rights": {"cleared": True, **rights},
            "generation": {"capability": capability, "pipeline": profile.id,
                           "providers": [p.name for p, _ in chain], "placeholder": placeholder,
                           "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True)
                                                            .encode()).hexdigest(),
                           "manifest": (generated_dir / MANIFEST).relative_to(job_dir).as_posix(),
                           **({"attribution": attribution[-1]} if attribution else {}),
                           **({"recipe": steps[-1]["metadata"]["recipe"]} if recipes else {})},
        }
        _bind(job, assets, name, spec, asset)
        manifest[name] = {"cache_key": key, "path": relative, "sha256": sha256_file(destination),
                          "asset": asset, "request": request, "steps": steps, **facts}
        return {"input": name, "capability": capability, "status": "generated", "path": relative,
                "providers": [p.name for p, _ in chain], "placeholder": placeholder,
                **({"fallbacks": failures} if failures else {}), **facts}
    raise ProductionError(f"Could not produce input {name!r}: " + " | ".join(failures))


def _bind(job: dict, assets: dict, name: str, spec: dict, asset: dict) -> None:
    asset_id = name if name not in assets or assets[name].get("generation") else f"generated_{name}"
    assets[asset_id] = asset
    job["inputs"][name] = asset_id
