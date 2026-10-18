"""One service layer behind every cockpit: the CLI, the Studio UI and the MCP server.

Each operation takes plain data and returns plain data (JSON-ready dicts), so
the three front ends behave the same. All files are written inside a
workspace directory; the pipeline profile is fixed by the operator when the
service starts and is never chosen by a request.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Iterable

from videogenome.compiler import ProductionError, compile_job, find_template, read_json, with_defaults
from videogenome.fill import TEXT_TYPES, check_values, describe_slots, slot_contracts
from videogenome.profile import Profile
from videogenome.requests import COPY_PROPERTIES, PREVIEW_PROPERTIES, RENDER_PROPERTIES, object_schema, validate_request

SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, fallback: str = "run") -> str:
    value = SLUG.sub("-", str(text).lower()).strip("-")[:40]
    return value or fallback


class Workspace:
    """Where every run writes: ``<root>/runs/<timestamp>-<slug>/``."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        (self.root / "runs").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def new_run(self, name: str) -> Path:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        with self._lock:
            for index in range(1000):
                path = self.root / "runs" / f"{stamp}-{slug(name)}{'' if index == 0 else f'-{index}'}"
                if not path.exists():
                    path.mkdir(parents=True)
                    return path
        raise ProductionError("Cannot allocate a run directory")

    def runs(self, limit: int = 50) -> list[dict]:
        validate_request({"limit": limit}, object_schema({"limit": {"type": "integer", "minimum": 1,
                                                                   "maximum": 1000}}))
        rows = []
        for path in sorted((self.root / "runs").iterdir(), reverse=True):
            if not path.is_dir() or not self.contains(path):
                continue
            summary = path / "summary.json"
            if summary.is_file() and self.contains(summary):
                try:
                    rows.append(read_json(summary))
                except ProductionError:
                    continue
                if len(rows) == limit:
                    break
        return rows

    def contains(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.root)


class Service:
    def __init__(self, profile: Profile, workspace: Workspace, *, template_dirs: Iterable[Path] = ()) -> None:
        self.profile = profile
        self.workspace = workspace
        self.template_dirs = list(template_dirs)

    # ---- discovery ------------------------------------------------------------
    def library(self, level: str | None = None, family: str | None = None) -> list[dict]:
        from videogenome.genomes import library
        return library(level=level, family=family)

    def genome(self, genome_id: str) -> dict:
        from videogenome.genomes import get
        entry = get(genome_id)
        return {**entry.describe(), "prompt_text": entry.prompt()}

    def templates(self) -> list[dict]:
        from videogenome.catalog import discover
        return [{k: e[k] for k in ("id", "version", "title", "description", "category", "tags", "duration_seconds",
                                   "self_contained", "shot_kinds")} | {"aspect_ratio": e["output"]["aspect_ratio"]}
                for e in discover(template_dirs=self.template_dirs)]

    def template(self, template_id: str) -> dict:
        from videogenome.catalog import inspect_template
        path = find_template(template_id, self.template_dirs)
        blueprint = read_json(path)
        contracts = slot_contracts(blueprint)
        media = {name: {"type": spec["type"], "required": spec["required"], "description": spec["description"],
                        "producible": "produce" in spec}
                 for name, spec in blueprint["inputs"].items() if spec["type"] not in TEXT_TYPES}
        return {
            "descriptor": inspect_template(template_id, self.template_dirs),
            "slots": contracts, "slots_text": describe_slots(contracts),
            "media_inputs": media,
            "renders_from_text_alone": all(not m["required"] or m["producible"] for m in media.values()),
            "copy_examples": blueprint.get("copy_examples", []),
            "quality_gates": blueprint["quality_gates"],
            "pipeline": self.profile.id,
        }

    def recipes(self, media: str | None = None) -> list[dict]:
        from videogenome.procedural import catalog
        return [r.describe() | {"params_schema": r.data["params"], "timing": r.data.get("timing", "frame"),
                                "libraries": r.data.get("libraries", [])}
                for r in catalog.discover().values() if not media or media in r.data["media"]]

    # ---- writing and checking copy ----------------------------------------------
    def check_inputs(self, template_id: str, inputs: dict, brief: str | None = None) -> dict:
        """The checks a writer's reply must pass, for copy written by anyone (agent, person, UI)."""
        validate_request({"template": template_id, "inputs": inputs, **({"brief": brief} if brief is not None else {})},
                         object_schema(COPY_PROPERTIES, ("template", "inputs")))
        blueprint = read_json(find_template(template_id, self.template_dirs))
        contracts = slot_contracts(blueprint)
        issues: list[dict] = []
        unknown = sorted(set(inputs) - set(contracts))
        for name in unknown:
            issues.append({"slots": [name], "problem": f"{name} is not a text slot of {template_id}"
                           + (" (media is produced by the pipeline or supplied as an asset)"
                              if name in blueprint["inputs"] else "")})
        values = {k: v for k, v in inputs.items() if k in contracts}
        effective = with_defaults(blueprint, values)
        for name, contract in contracts.items():
            if contract["required"] and effective.get(name) in (None, "", []):
                issues.append({"slots": [name], "problem": f"{name} is required: {contract['description']}"})
        # Keep supplied empty and null values: dropping them could make Check pass
        # a value that the compiler later rejects (e.g. an optional numeric slot).
        found = check_values(blueprint, contracts, values, brief or "", renderer=self.profile.renderer())
        unverified = []
        if brief is None:  # Without the brief, verbatim grounding cannot be checked.
            unverified = sorted({s for i in found if i.get("kind") == "verbatim" for s in i["slots"]})
            found = [i for i in found if i.get("kind") != "verbatim"]
        # Word budgets estimate speaking time; the produced speech is measured and decides.
        warnings = [i for i in found if i.get("kind") == "estimate"]
        issues += [i for i in found if i.get("kind") != "estimate"]
        return {"ok": not issues, "issues": issues, "warnings": warnings, "verbatim_unverified": unverified,
                "note": ("Verbatim slots were not checked: pass the brief so names, quotes and numbers "
                         "can be matched against it.") if unverified else None}

    def fill(self, template_id: str, brief: str, pinned: dict | None = None, max_attempts: int = 3) -> dict:
        from videogenome.create import make_filler
        result = make_filler(template_id, brief, self.profile, template_dirs=self.template_dirs,
                             pinned=pinned, max_attempts=max_attempts).run()
        return {"status": result.status, "inputs": result.job["inputs"], "missing": result.missing,
                "issues": result.issues, "attempts": len(result.record["attempts"]),
                "writer": result.record["writer"]}

    # ---- producing videos ------------------------------------------------------------
    def render(self, template_id: str, inputs: dict, *, brief: str | None = None, author: str = "person",
               name: str | None = None, log: Callable[[str], None] = lambda _: None) -> dict:
        """Write a job from finished copy, produce its media with the operator's pipeline, render, gate."""
        from videogenome.pipeline import run_render
        from videogenome.produce import produce
        check = self.check_inputs(template_id, inputs, brief)
        if not check["ok"]:
            raise ProductionError("Inputs do not fit the template: " + "; ".join(
                f"{', '.join(i['slots'])}: {i['problem']}" for i in check["issues"][:8]))
        blueprint = read_json(find_template(template_id, self.template_dirs))
        run = self.workspace.new_run(name or template_id.split(".")[-1])
        job = {"job_schema": "0.1.0", "id": f"run.{slug(run.name)}", "template": template_id,
               "template_version": blueprint["version"], "inputs": inputs, "assets": {}, "shot_assets": {},
               "approved_gates": []}
        job_path = run / "job.json"
        job_path.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        context = None
        if author != "person" or brief:
            context = {"fill": {"status": "complete", "writer": {"name": author, "type": "external"},
                                "attempts": 1, "brief": brief or "", "written_inputs": sorted(inputs),
                                "caveat": "Copy was supplied by an external author (person or agent) and "
                                          "checked against the template's slot contracts"
                                          + (" and the brief." if brief else "; no brief was given, so "
                                             "verbatim facts were not matched against one.")}}
        log("producing media")
        produced, report = produce(job_path, self.profile, template_dirs=self.template_dirs)
        log("rendering")
        plan = compile_job(produced, template_dirs=self.template_dirs)
        output = run / f"{slug(template_id.split('.')[-1])}.mp4"
        receipt = run_render(plan, produced.parent, output, self.profile, context=context)
        (run / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return self._summarise(run, template_id, receipt, report)

    def create(self, template_id: str, brief: str, *, pinned: dict | None = None, name: str | None = None,
               log: Callable[[str], None] = lambda _: None) -> dict:
        """Brief to video with the operator's writer (fill, produce, render)."""
        from videogenome.create import create
        run = self.workspace.new_run(name or template_id.split(".")[-1])
        output = run / f"{slug(template_id.split('.')[-1])}.mp4"
        receipt, result, _ = create(template_id, brief, self.profile, output, template_dirs=self.template_dirs,
                                    pinned=pinned, workdir=run / "job", log=log)
        (run / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return self._summarise(run, template_id, receipt, [])

    # ---- previews for the library ---------------------------------------------------------
    @property
    def previews_dir(self) -> Path:
        path = self.workspace.root / "previews"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sample_jobs(self) -> dict[str, Path]:
        """Template id -> bundled sample job (examples/<name>/job.json)."""
        from videogenome.resources import DATA_ROOT
        roots = [DATA_ROOT / "examples", *(Path(d).parent / "examples" for d in self.template_dirs)]
        found: dict[str, Path] = {}
        for root in roots:
            for path in sorted(root.glob("*/job.json")) if root.is_dir() else []:
                try:
                    found.setdefault(read_json(path)["template"], path)
                except (ProductionError, KeyError):
                    continue
        return found

    def build_preview(self, template_id: str, log: Callable[[str], None] = lambda _: None) -> dict:
        job = self.sample_jobs().get(template_id)
        if job is None:
            raise ProductionError(f"No sample job ships for {template_id}")
        info = self.template(template_id)
        if not info["renders_from_text_alone"]:
            raise ProductionError(f"{template_id} needs supplied media; no preview from text alone")
        inputs = {k: v for k, v in read_json(job)["inputs"].items() if k in info["slots"]}
        result = self.render(template_id, inputs, name=f"preview-{template_id}", log=log)
        if result["contains_placeholder_media"]:
            # A library card must show what the template makes, never an animatic stand-in.
            raise ProductionError(f"{template_id}: pipeline {self.profile.id!r} produced placeholder media; "
                                  "build its preview with a pipeline that produces real media")
        shutil.copyfile(result["output"], self.previews_dir / f"{template_id}.mp4")
        if result.get("poster"):
            shutil.copyfile(result["poster"], self.previews_dir / f"{template_id}.jpg")
        return result

    def _summarise(self, run: Path, template_id: str, receipt: dict, report: list[dict]) -> dict:
        deliverables = {k: v["path"] for k, v in receipt["deliverables"].items()}
        summary = {
            "run": run.name, "directory": str(run), "template": template_id, "kind": "template",
            "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "output": receipt["output_path"], "review_page": deliverables.get("review_page"),
            "contact_sheet": deliverables.get("contact_sheet"), "poster": deliverables.get("poster"),
            "receipt": str(run / "receipt.json"),
            "duration_seconds": receipt["duration_observed_seconds"],
            "gates": {g["id"]: g["status"] for g in receipt["quality_gates"]},
            "automated_gates_failed": [g["id"] for g in receipt["quality_gates"] if g["status"] == "failed"],
            "contains_placeholder_media": receipt["contains_placeholder_media"],
            "loudness_lufs": receipt["measurements"].get("integrated_lufs"),
            "produced": [{k: e.get(k) for k in ("input", "status", "providers", "placeholder")} for e in report],
        }
        (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary

    # ---- code: recipes and arbitrary pages -----------------------------------------------
    def preview_recipe(self, recipe_id: str, *, preset: str | None = None, params: dict | None = None,
                       size: str = "1280x720", fps: int = 30, duration: float = 6.0, seed: int = 1,
                       still: bool = False) -> dict:
        from videogenome.providers.procedural import ProceduralProvider
        validate_request({"recipe": recipe_id, "size": size, "fps": fps, "duration": duration, "seed": seed,
                          "params": params if params is not None else {},
                          **({"preset": preset} if preset is not None else {})},
                         object_schema(PREVIEW_PROPERTIES, ("recipe",)))
        width, height = _size(size)
        run = self.workspace.new_run(recipe_id)
        media = "image" if still else ("audio" if recipe_id.startswith("audio.") else "video")
        request = {"recipe": recipe_id, "media": media, "width": width, "height": height, "fps": fps,
                   "duration_seconds": duration, "seed": seed, "params": params or {}}
        if preset:
            request["preset"] = preset
        with tempfile.TemporaryDirectory(prefix="videogenome-preview-") as directory:
            result = ProceduralProvider("procedural", {}).generate("procedural", request, Path(directory))
            output = run / f"{slug(recipe_id)}{result.path.suffix}"
            shutil.copyfile(result.path, output)
        sheet = contact_sheet(output, run / "contact.jpg") if media == "video" else None
        summary = {"run": run.name, "directory": str(run), "kind": "recipe", "recipe": recipe_id,
                   "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                   "output": str(output), "contact_sheet": str(sheet) if sheet else None,
                   "params": result.metadata["recipe"]["params"], "preset": preset}
        (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary

    def capture(self, *, html: str | None = None, page: Path | None = None, size: str = "1920x1080",
                fps: int = 30, duration: float = 10.0, seed: int = 1, click: bool | list | None = None,
                audio: bool = True, params: dict | None = None, name: str = "capture") -> dict:
        """Render HTML code exactly as written (an agent's or a person's), frame-exact on the virtual clock."""
        _capture_settings(size, fps, duration, seed, params)
        if html is not None and (not isinstance(html, str) or not html.strip()):
            raise ProductionError("html must be a nonempty string")
        if html is None and page is None:
            raise ProductionError("Give html (the page source) or a page path")
        run = self.workspace.new_run(name)
        if html is not None:
            page = run / "index.html"
            page.write_text(html, encoding="utf-8")
        assert page is not None
        output = run / "capture.mp4"
        info = capture_page(page, output, size=size, fps=fps, duration=duration, seed=seed, click=click,
                            audio=audio, params=params)
        sheet = contact_sheet(output, run / "contact.jpg")
        summary = {"run": run.name, "directory": str(run), "kind": "capture", "page": str(page),
                   "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                   "output": str(output), "contact_sheet": str(sheet) if sheet else None, **info}
        (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary


def _size(size: str) -> tuple[int, int]:
    width, _, height = str(size).partition("x")
    if not (width.isdigit() and height.isdigit()) or int(width) % 2 or int(height) % 2:
        raise ProductionError("size must be WIDTHxHEIGHT with even numbers, e.g. 1080x1920")
    width_px, height_px = int(width), int(height)
    if not (16 <= width_px <= 4096 and 16 <= height_px <= 4096):
        raise ProductionError("size must be between 16 and 4096 pixels per side")
    return width_px, height_px


def _capture_settings(size: str, fps: int, duration: float, seed: int, params: dict | None) -> tuple[int, int]:
    validate_request({"size": size, "fps": fps, "duration": duration, "seed": seed,
                      "params": params if params is not None else {}}, object_schema(RENDER_PROPERTIES))
    return _size(size)


def capture_page(page: Path, output: Path, *, size: str = "1920x1080", fps: int = 30, duration: float = 10.0,
                 seed: int = 1, click: bool | list | None = None, audio: bool = True, params: dict | None = None,
                 at: float | None = None, timing: str = "clock") -> dict:
    """Run a self-contained page on the virtual clock and encode it (the engine behind `capture`)."""
    from videogenome.procedural.catalog import bundled_libraries
    from videogenome.render import probe
    width, height = _capture_settings(size, fps, duration, seed, params)
    validate_request({"timing": timing, **({"at": at} if at is not None else {})},
                     object_schema({"timing": {"enum": ["clock", "frame"]},
                                    "at": {"type": "number", "minimum": 0, "maximum": 600}}))
    page = page.resolve()
    if not page.is_file() or page.suffix.lower() not in (".html", ".htm"):
        raise ProductionError(f"Not an HTML file: {page}")
    media = {".mp4": "video", ".png": "image", ".jpg": "image"}.get(output.suffix.lower())
    if media is None:
        raise ProductionError("Output must end in .mp4, .png or .jpg")
    spec = {"media": media, "width": width, "height": height, "fps": fps, "duration_seconds": duration,
            "seed": seed, "params": params or {}, **({"mode": "clock"} if timing == "clock" else {}),
            **({"still_seconds": at} if at is not None else {}),
            **({"audio": True} if media == "video" and timing == "clock" and audio else {}),
            **({"click": click} if click else {})}
    output.parent.mkdir(parents=True, exist_ok=True)
    libraries = [arg for lib, path in bundled_libraries().items() for arg in ("--lib", f"{lib}={path}")]
    with tempfile.TemporaryDirectory(prefix="videogenome-capture-") as directory:
        spec_path = Path(directory) / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-m", "videogenome.procedural.browser", "--entry", str(page),
             "--spec", str(spec_path), "--out", str(output.resolve()), *libraries],
            capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ProductionError(f"Capture failed: {(completed.stderr or completed.stdout).strip()[-1200:]}")
    info = {"media": media, "size": f"{width}x{height}", "fps": fps, "duration_seconds": duration}
    if media == "video":
        frames = next((int(s.get("nb_read_frames", 0)) for s in probe(output, count_frames=True)["streams"]
                       if s.get("codec_type") == "video"), 0)
        expected = max(1, round(duration * fps))
        if frames != expected:
            raise ProductionError(f"Captured {frames} frames, expected {expected}")
        info["frames"] = frames
        info["audio"] = ("recorded" if "VG_AUDIO=recorded" in completed.stdout
                         else "silent" if "VG_AUDIO=silent" in completed.stdout else "none")
    return info


def contact_sheet(video: Path, output: Path, *, tiles: int = 8, width: int = 360) -> Path | None:
    """A strip of evenly spaced frames, for people and for agents that can see images."""
    from videogenome.render import probe
    try:
        stream = next(s for s in probe(video, count_frames=True)["streams"] if s.get("codec_type") == "video")
    except (StopIteration, ProductionError):
        return None
    frames = int(stream.get("nb_read_frames", 0))
    if frames <= 0:
        return None
    count = min(tiles, frames)
    picks = sorted({min(frames - 1, round((i + 0.5) * frames / count)) for i in range(count)})
    columns = min(4, len(picks))
    rows = -(-len(picks) // columns)
    select = "+".join(f"eq(n\\,{n})" for n in picks)
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf",
         f"select='{select}',scale={width}:-2,tile={columns}x{rows}:padding=6:margin=6:color=0x101010",
         "-fps_mode", "passthrough", "-frames:v", "1", "-q:v", "3", str(output)],
        capture_output=True, text=True, check=False)
    return output if completed.returncode == 0 and output.is_file() else None
