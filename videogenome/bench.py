"""Measure how well a writer fills templates from briefs.

VideoGenome's claim is that a small model can produce credible videos by
filling expert-locked templates. ``videogenome bench`` turns that into
numbers for one pipeline's writer: how often a brief becomes a valid job, on
which attempt, how long it takes, and whether the writer correctly refuses
briefs that lack required facts. With ``--render`` every completed job is also
produced, rendered and gated.

A suite is JSON:

    {"suite_schema": "0.1.0", "briefs": [
      {"id": "garlic", "template": "social.vertical-tips", "brief": "...",
       "set": {"energy": "upbeat"}, "expect": "complete"},
      {"id": "no-transcript", "template": "social.ugc-testimonial", "brief": "...",
       "expect": "incomplete"}]}

Bench measures validity, honesty and timing. It does not judge whether the
copy is good; that remains a human (or separate evaluator) decision.
"""
from __future__ import annotations

import datetime as _dt
import json
import statistics
import time
from pathlib import Path
from typing import Callable, Iterable

from jsonschema import Draft202012Validator

from videogenome.compiler import ProductionError, read_json
from videogenome.create import FillIncomplete, create, make_filler
from videogenome.profile import Profile

SUITE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["suite_schema", "briefs"],
    "properties": {
        "suite_schema": {"const": "0.1.0"},
        "description": {"type": "string"},
        "briefs": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "template", "brief"],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
                "template": {"type": "string"},
                "brief": {"type": "string", "minLength": 10},
                "set": {"type": "object"},
                "expect": {"enum": ["complete", "incomplete"]},
                "note": {"type": "string"}}}},
    },
}


def load_suite(path: Path) -> dict:
    suite = read_json(path)
    errors = sorted(Draft202012Validator(SUITE_SCHEMA).iter_errors(suite), key=lambda e: list(e.absolute_path))
    if errors:
        raise ProductionError(f"Invalid suite {path}: " + "; ".join(
            f"/{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:6]))
    ids = [entry["id"] for entry in suite["briefs"]]
    if len(ids) != len(set(ids)):
        raise ProductionError(f"Suite {path} repeats brief ids")
    return suite


def run_bench(suite_path: Path, profile: Profile, *, template_dirs: Iterable[Path] = (),
              render_dir: Path | None = None, max_attempts: int = 3,
              log: Callable[[str], None] = print) -> dict:
    suite = load_suite(suite_path)
    template_dirs = list(template_dirs)
    rows = []
    for entry in suite["briefs"]:
        expect = entry.get("expect", "complete")
        started = time.monotonic()
        row: dict = {"id": entry["id"], "template": entry["template"], "expect": expect}
        try:
            if render_dir is not None and expect == "complete":
                receipts, result, job_path = create(
                    entry["template"], entry["brief"], profile, render_dir / f"{entry['id']}.mp4",
                    template_dirs=template_dirs, pinned=entry.get("set"), max_attempts=max_attempts,
                    log=lambda _: None)
                receipt = next(iter(receipts.values()))
                gates = {g["id"]: g["status"] for g in receipt["quality_gates"]}
                row["render"] = {"output": receipt["output_path"], "gates": gates,
                                 "automated_failed": sorted(k for k, v in gates.items() if v == "failed")}
            else:
                result = make_filler(entry["template"], entry["brief"], profile, template_dirs=template_dirs,
                                     pinned=entry.get("set"), max_attempts=max_attempts).run()
            row.update({
                "status": result.status, "attempts": len(result.record["attempts"]),
                "writer_seconds": round(sum(a["seconds"] for a in result.record["attempts"]), 2),
                "inputs": {k: result.job["inputs"][k] for k in result.record["written_inputs"]},
                "missing": [m["input"] for m in result.missing],
                "unresolved": [f"{', '.join(i['slots'])}: {i['problem']}" for i in result.issues],
                "first_attempt_issues": [f"{', '.join(i['slots'])}: {i['problem']}"
                                         for i in result.record["attempts"][0]["issues"]],
            })
        except ProductionError as exc:
            status = "incomplete" if isinstance(exc, FillIncomplete) else "error"
            row.update({"status": status, "error": str(exc)})
        row["seconds"] = round(time.monotonic() - started, 2)
        row["as_expected"] = row["status"] == expect and not row.get("render", {}).get("automated_failed")
        mark = "ok " if row["as_expected"] else "BAD"
        log(f"{mark} {entry['id']:<24} {entry['template']:<34} {row['status']:<10} "
            f"attempts={row.get('attempts', '-')} {row['seconds']:.1f}s")
        rows.append(row)

    complete_expected = [r for r in rows if r["expect"] == "complete"]
    refusals = [r for r in rows if r["expect"] == "incomplete"]
    filled = [r for r in complete_expected if r["status"] == "complete"]
    summary = {
        "briefs": len(rows),
        "as_expected": sum(r["as_expected"] for r in rows),
        "fill_rate": round(len(filled) / len(complete_expected), 3) if complete_expected else None,
        "first_attempt_rate": (round(sum(r["attempts"] == 1 for r in filled) / len(complete_expected), 3)
                               if complete_expected else None),
        "mean_attempts": round(statistics.mean(r["attempts"] for r in filled), 2) if filled else None,
        "median_writer_seconds": (round(statistics.median(r["writer_seconds"] for r in filled), 2)
                                  if filled else None),
        "honest_refusal_rate": (round(sum(r["status"] == "incomplete" for r in refusals) / len(refusals), 3)
                                if refusals else None),
        "renders_with_failed_gates": sum(bool(r.get("render", {}).get("automated_failed")) for r in rows),
    }
    writer = profile.writer().describe()
    return {"bench_schema": "0.1.0",
            "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "suite": str(suite_path), "pipeline": profile.id, "writer": writer,
            "summary": summary, "results": rows,
            "caveat": "Measures validity, honesty about missing facts and timing, not copy quality."}
