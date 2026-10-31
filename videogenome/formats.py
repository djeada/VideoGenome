"""Delivery formats: one template, one job, several frame geometries.

A blueprint's ``output`` is its main format. ``output.formats`` (schema 0.6.0)
lists the other aspect ratios the template is authored and reviewed for, keyed
by aspect id (``9x16``, ``1x1``, ``4x5``). Each entry gives the frame size and
may restate the pixel-valued typography (title card, caption style) for that
frame. Story, timing, copy contracts, audio and gates are shared: a format is
the same video laid out again by its renderer, not a different template.

Copy written for a template must fit every one of its formats, so any later
multi-format render of the same job succeeds without rewriting.
"""
from __future__ import annotations

import copy
import re
from math import gcd
from pathlib import Path

FORMAT_ID = re.compile(r"^[1-9][0-9]?x[1-9][0-9]?$")
ALL = "all"


def aspect_id(width: int, height: int) -> str:
    divisor = gcd(width, height)
    return f"{width // divisor}x{height // divisor}"


def label(format_id: str) -> str:
    """Display form: ``9x16`` -> ``9:16``."""
    return format_id.replace("x", ":")


def normalise(value: str) -> str:
    return str(value).strip().lower().replace(":", "x")


def main_format(blueprint: dict) -> str:
    return aspect_id(blueprint["output"]["width"], blueprint["output"]["height"])


def format_ids(blueprint: dict) -> list[str]:
    """Every format the template renders, its main format first."""
    return [main_format(blueprint), *blueprint["output"].get("formats", {})]


def _error(message: str) -> Exception:
    from videogenome.compiler import ProductionError  # Late: the compiler imports this module.
    return ProductionError(message)


def apply_format(blueprint: dict, format_id: str | None = None) -> dict:
    """The blueprint as rendered in one format, with ``output.formats`` removed.

    ``None`` selects the main format. The result is a copy; the source is untouched.
    """
    main = main_format(blueprint)
    wanted = main if format_id is None else normalise(format_id)
    variant = copy.deepcopy(blueprint)
    formats = variant["output"].pop("formats", {})
    if wanted == main:
        return variant
    spec = formats.get(wanted)
    if spec is None:
        raise _error(f"Template {blueprint.get('id')!r} has no {label(wanted)} format; "
                     f"it renders {', '.join(label(f) for f in format_ids(blueprint))}")
    variant["output"]["width"], variant["output"]["height"] = spec["width"], spec["height"]
    if "title_card" in spec:
        variant["style"]["title_card"] = {**variant["style"].get("title_card", {}), **spec["title_card"]}
    if "caption_style" in spec:
        captions = variant.get("timeline", {}).get("captions")
        if captions:
            captions["style"] = {**captions["style"], **spec["caption_style"]}
    return variant


def variants(blueprint: dict) -> list[tuple[str, dict]]:
    """``(format_id, blueprint_in_that_format)`` for every format, main first."""
    return [(format_id, apply_format(blueprint, format_id)) for format_id in format_ids(blueprint)]


def resolve(blueprint: dict, requested: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalise a request (ids, ``9:16`` labels or ``all``) to known format ids, in order."""
    available = format_ids(blueprint)
    if not requested:
        return [available[0]]
    chosen: list[str] = []
    for item in requested:
        for part in str(item).split(","):
            value = normalise(part)
            if not value:
                continue
            names = available if value == ALL else [value]
            for name in names:
                if name not in available:
                    raise _error(f"Template {blueprint.get('id')!r} has no {label(name)} format; "
                                 f"it renders {', '.join(label(f) for f in available)}")
                if name not in chosen:
                    chosen.append(name)
    return chosen or [available[0]]


def output_path(output: Path, format_id: str, several: bool) -> Path:
    """Where one format's file goes: ``promo.mp4`` -> ``promo.9x16.mp4`` when rendering several."""
    return output.with_name(f"{output.stem}.{format_id}{output.suffix}") if several else output


def job_stem(path: Path) -> str:
    """A job file's own name without ``.produced`` or a format suffix: ``job.9x16.produced`` -> ``job``."""
    stem = path.stem.removesuffix(".produced")
    head, _, tail = stem.rpartition(".")
    return head if head and FORMAT_ID.match(tail) else stem


def errors(data: dict) -> list[str]:
    """Cross-field checks for ``output.formats`` (run after the schema passes)."""
    formats = data["output"].get("formats")
    if not formats:
        return []
    problems = []
    main = main_format(data)
    for format_id, spec in formats.items():
        actual = aspect_id(spec["width"], spec["height"])
        if actual != format_id:
            problems.append(f"output.formats.{format_id}: {spec['width']}x{spec['height']} is "
                            f"{label(actual)}, not {label(format_id)}")
        if format_id == main:
            problems.append(f"output.formats.{format_id}: duplicates the main output format")
        if spec["width"] % 2 or spec["height"] % 2:
            problems.append(f"output.formats.{format_id}: H.264 delivery needs even frame dimensions")
        if "title_card" in spec and "title_card" not in data["style"]:
            problems.append(f"output.formats.{format_id}: title_card overrides need a declared style.title_card")
        if "caption_style" in spec and "captions" not in data.get("timeline", {}):
            problems.append(f"output.formats.{format_id}: caption_style overrides need timeline captions")
    return problems
