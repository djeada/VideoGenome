"""Brief to finished video: fill text slots, produce media, render, measure.

``create`` chains the same stages a person would run by hand (``fill``,
``produce``, ``render``) and adds one feedback edge: when produced narration
overruns its locked slot, the measured length goes back to the writer, which
shortens exactly the copy that feeds it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable

from videogenome.compiler import ProductionError, compile_job
from videogenome.fill import Filler, FillResult, load_for_fill, narration_slots
from videogenome.pipeline import run_render
from videogenome.produce import CopyTooLong, produce
from videogenome.profile import Profile


class FillIncomplete(ProductionError):
    """The brief lacks what required inputs need; the writer said so instead of guessing."""


def fill_paths(job_path: Path) -> Path:
    return job_path.with_name(f"{job_path.stem}.fill.json")


def save_fill(result: FillResult, job_path: Path) -> Path:
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(result.job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    record = fill_paths(job_path)
    record.write_text(json.dumps(result.record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def make_filler(reference: str, brief: str, profile: Profile, *, template_dirs: Iterable[Path] = (),
                pinned: dict | None = None, max_attempts: int = 3, job_id: str | None = None) -> Filler:
    blueprint, template_path, job, _ = load_for_fill(reference, template_dirs)
    return Filler(blueprint, template_path, profile.writer(), brief=brief, renderer=profile.renderer(),
                  pinned=pinned, base_job=job, job_id=job_id, max_attempts=max_attempts,
                  pipeline_id=profile.id)


def explain(result: FillResult) -> str:
    if result.status == "incomplete":
        return "the brief lacks what these inputs need: " + "; ".join(
            f"{m['input']} ({m['reason'] or 'no reason given'})" for m in result.missing)
    return "the writer's copy still breaks the template after every attempt: " + "; ".join(
        f"{', '.join(i['slots']) or 'reply'}: {i['problem']}" for i in result.issues[:6])


def _require_complete(result: FillResult, output: Path) -> None:
    if result.status == "incomplete":
        raise FillIncomplete(f"Cannot create {output.name}: {explain(result)}")
    if result.status != "complete":
        raise ProductionError(f"Cannot create {output.name}: {explain(result)}")


def create(reference: str, brief: str, profile: Profile, output: Path, *,
           template_dirs: Iterable[Path] = (), pinned: dict | None = None, max_attempts: int = 3,
           workdir: Path | None = None, revisions: int = 2, write_deliverables: bool = True,
           log: Callable[[str], None] = print) -> tuple[dict, FillResult, Path]:
    """Return ``(receipt, fill_result, job_path)``; raise if any stage cannot finish."""
    template_dirs = list(template_dirs)
    workdir = (workdir or output.parent / f"{output.stem}.job").resolve()
    job_path = workdir / "job.json"
    filler = make_filler(reference, brief, profile, template_dirs=template_dirs, pinned=pinned,
                         max_attempts=max_attempts)
    result = filler.run()
    save_fill(result, job_path)
    log(f"Fill:     {result.status} after {len(result.record['attempts'])} attempt(s) -> {job_path}")
    _require_complete(result, output)

    for revision in range(revisions + 1):
        try:
            produced, report = produce(job_path, profile, template_dirs=template_dirs)
            break
        except CopyTooLong as exc:
            slots = [s for s in narration_slots(filler.blueprint, exc.input) if s in filler.contracts]
            if not slots or revision == revisions:
                raise
            words = sum(len(str(filler.values.get(s, "")).split()) for s in slots)
            target = max(3, math.floor(words * exc.need / exc.seconds * 0.9))
            log(f"Revise:   {exc.input} spoke {exc.seconds:.1f}s in a {exc.need:.1f}s slot; "
                f"asking the writer for at most {target} words")
            result = filler.revise([{"slots": slots, "problem": (
                f"spoken aloud this runs {exc.seconds:.1f} s but the narration slot is {exc.need:.1f} s; "
                f"rewrite it in at most {target} words")}])
            save_fill(result, job_path)
            _require_complete(result, output)
    for entry in report:
        flag = "  [PLACEHOLDER]" if entry.get("placeholder") else ""
        log(f"Produce:  {entry['status']:<10} {entry['input']:<22} {' -> '.join(entry.get('providers', []))}{flag}")
    plan = compile_job(produced, template_dirs=template_dirs)
    fill = {"record": str(fill_paths(job_path)), "status": result.status, "writer": result.record["writer"],
            "attempts": len(result.record["attempts"]), "brief": result.record["brief"],
            "written_inputs": result.record["written_inputs"], "caveat": result.record["caveat"]}
    receipt = run_render(plan, produced.parent, output, profile, write_deliverables=write_deliverables,
                         context={"fill": fill})
    return receipt, result, job_path
