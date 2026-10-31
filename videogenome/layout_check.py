"""Check that copy fits code-rendered scenes in every delivery format, without rendering.

Scene recipes measure their copy with real glyphs and throw when it cannot fit
the frame. This loads each browser recipe a job would produce, with the exact
params and frame size a render would use, steps its clock through the
programme without capturing frames, and reports what the page threw: the same
error a render would hit, in seconds, for every format at once.

Only browser recipes are checked (Python recipes draw no measured copy). The
check needs Playwright and Chromium; ``available()`` says whether it can run,
and callers report a check that did not run rather than claiming it passed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from videogenome.compiler import ProductionError, with_defaults
from videogenome.formats import label, resolve, variants

SLOT = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
TIMEOUT_SECONDS = 300


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def renders_recipes(profile) -> bool:
    """Whether the pipeline renders ``procedural`` requests with the recipe catalog (else layout is moot)."""
    from videogenome.providers.procedural import ProceduralProvider
    try:
        return any(isinstance(profile.provider(alternative[-1][0]), ProceduralProvider)
                   for alternative in profile.routes_for("procedural"))
    except Exception:  # noqa: BLE001 - a broken profile is reported by doctor, not here
        return False


def _slots(value) -> set[str]:
    if isinstance(value, str):
        return set(SLOT.findall(value))
    if isinstance(value, dict):
        return set().union(*map(_slots, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(_slots, value)) if value else set()
    return set()


def scene_items(blueprint: dict, inputs: dict, *, job_id: str = "check") -> list[dict]:
    """One check item per browser recipe the job would produce in this (format-applied) blueprint.

    Inputs the job supplies itself, and requests whose slots are not all filled
    yet, are skipped. Invalid recipe params are returned as ready-made errors.
    """
    from videogenome.procedural import catalog
    from videogenome.produce import _request
    from videogenome.providers.procedural import recipe_spec
    values = with_defaults(blueprint, inputs)
    job = {"id": job_id, "inputs": values}
    items = []
    for name, spec in blueprint["inputs"].items():
        produce = spec.get("produce")
        if not produce or produce["capability"] != "procedural" or name in inputs:
            continue
        slots = sorted(_slots(produce.get("request", {})))
        try:
            recipe = catalog.get(produce["request"]["recipe"])
        except (KeyError, ProductionError):
            continue
        if recipe.data["runtime"] != "browser" or spec["type"] not in ("video", "image"):
            continue
        if any(slot not in values for slot in slots if blueprint["inputs"][slot].get("required")):
            continue
        item = {"input": name, "slots": slots}
        try:
            request = _request(blueprint, job, name, spec, None, {}, Path("."))
            run = recipe_spec(recipe, request, request["media"], request.get("preset"), request.get("params"))
        except ProductionError as exc:
            message = str(exc)
            if "needs text input" in message:  # An optional slot the request uses is still empty.
                continue
            items.append({**item, "error": message})
            continue
        libraries = dict(zip(recipe.data.get("libraries", []), map(str, recipe.libraries())))
        items.append({**item, "page": {"entry": str(recipe.entry), "root": str(recipe.root),
                                       "allow": [str(recipe.directory)], "lib": libraries, "spec": run}})
    return items


def run_checks(pages: list[dict]) -> list[str | None]:
    """Load every page in one browser session; return the first error each raised (or None)."""
    if not pages:
        return []
    with tempfile.TemporaryDirectory(prefix="videogenome-layout-") as directory:
        batch, out = Path(directory) / "batch.json", Path(directory) / "results.json"
        batch.write_text(json.dumps(pages), encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "videogenome.procedural.browser", "--check", str(batch), "--out", str(out)],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ProductionError(f"Layout check timed out after {TIMEOUT_SECONDS}s") from exc
        if completed.returncode or not out.is_file():
            raise ProductionError("Layout check could not run: " + (completed.stderr.strip()[-400:] or "no output"))
        return [row.get("error") for row in json.loads(out.read_text(encoding="utf-8"))]


def _clean(error: str) -> str:
    return re.sub(r"^(Uncaught )?(Error|TypeError|RangeError): ", "", error.strip()).splitlines()[0]


def _blamed(item: dict, inputs: dict, error: str) -> list[str]:
    """The slots an error quotes (recipes quote up to 40 characters of the text), else all it uses."""
    def texts(value):
        return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] \
            if isinstance(value, list) else []
    quoted = [slot for slot in item["slots"]
              if any(text.strip() and text.strip()[:40] in error for text in texts(inputs.get(slot)))]
    return quoted or item["slots"]


def layout_issues(blueprint: dict, inputs: dict, formats: list[str] | None = None) -> list[dict]:
    """Problems with ``inputs`` in each requested format (default: every format), as check issues.

    Each issue is ``{"slots", "kind": "layout", "problem", "formats"}``; a problem
    seen in only some formats names them.
    """
    return layout_issues_many([(blueprint, inputs, formats)])[0]


def layout_issues_many(cases: list[tuple[dict, dict, list[str] | None]]) -> list[list[dict]]:
    """``layout_issues`` for several ``(blueprint, inputs, formats)`` cases in one browser session."""
    work = []  # (case index, format id, item)
    views_per_case = []
    for index, (blueprint, inputs, formats) in enumerate(cases):
        wanted = resolve(blueprint, formats or ["all"])
        views = [(format_id, view) for format_id, view in variants(blueprint) if format_id in wanted]
        views_per_case.append(len(views))
        work += [(index, format_id, item) for format_id, view in views for item in scene_items(view, inputs)]
    results = iter(run_checks([item["page"] for _, _, item in work if "page" in item]))
    found: list[dict[tuple, list[str]]] = [{} for _ in cases]
    for index, format_id, item in work:
        error = item["error"] if "error" in item else next(results)
        if error:
            recipe = item["page"]["spec"]["recipe"] if "page" in item else "recipe"
            problem = f"{item['input']} ({recipe}): {_clean(error)}"
            found[index].setdefault((tuple(_blamed(item, cases[index][1], error)), problem), []).append(format_id)
    reports = []
    for index, problems in enumerate(found):
        issues = []
        for (slots, problem), where in problems.items():
            if len(where) < views_per_case[index]:
                problem = f"in the {', '.join(label(f) for f in where)} format: {problem}"
            issues.append({"slots": list(slots), "kind": "layout", "problem": problem, "formats": where})
        reports.append(issues)
    return reports
