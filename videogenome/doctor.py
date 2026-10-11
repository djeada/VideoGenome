"""Environment diagnostics: can this machine render the catalog faithfully?"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from videogenome.compiler import ProductionError

REQUIRED_FILTERS = ("drawtext", "xfade", "acrossfade", "ebur128", "loudnorm", "blackdetect",
                    "silencedetect", "signalstats", "amix", "alimiter", "tile")


def _output(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return completed.stdout + completed.stderr


def diagnose(template_dirs: Iterable[Path] = ()) -> list[tuple[str, str, str]]:
    """Return (OK|WARN|FAIL, check, detail) rows."""
    rows = []
    version = sys.version_info
    rows.append(("OK" if version >= (3, 10) else "FAIL", "python",
                 f"{version.major}.{version.minor}.{version.micro} (3.10+ required)"))
    try:
        from importlib.metadata import version as package_version
        rows.append(("OK", "jsonschema", package_version("jsonschema")))
    except Exception:  # noqa: BLE001 - any failure means it is unusable
        rows.append(("FAIL", "jsonschema", "not installed: pip install jsonschema"))

    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        detail = _output([tool, "-version"]).splitlines()[0] if path else "not found on PATH"
        rows.append(("OK" if path else "FAIL", tool, detail))
    if not shutil.which("ffmpeg"):
        return rows

    filters = _output(["ffmpeg", "-hide_banner", "-filters"])
    missing = [name for name in REQUIRED_FILTERS if f" {name} " not in filters]
    rows.append(("FAIL" if missing else "OK", "ffmpeg filters",
                 f"missing: {', '.join(missing)}" if missing else f"{len(REQUIRED_FILTERS)} required present"))
    drawtext = _output(["ffmpeg", "-hide_banner", "-h", "filter=drawtext"])
    rows.append(("OK" if "y_align" in drawtext else "FAIL", "drawtext baseline alignment",
                 "y_align available" if "y_align" in drawtext else "FFmpeg 6.1+ required for y_align"))
    encoders = _output(["ffmpeg", "-hide_banner", "-encoders"])
    for encoder in ("libx264", "aac"):
        present = f" {encoder} " in encoders
        rows.append(("OK" if present else "FAIL", f"encoder {encoder}", "present" if present else "missing"))

    if not shutil.which("fc-match"):
        rows.append(("WARN", "fontconfig", "fc-match missing: fonts cannot be pinned or recorded"))
        return rows
    rows.append(("OK", "fontconfig", "fc-match available"))
    from videogenome.catalog import discover
    from videogenome.layout import WEIGHTS
    try:
        catalog = discover(template_dirs=template_dirs)
    except ProductionError as exc:
        rows.append(("FAIL", "template catalog", str(exc)))
        return rows
    rows.append(("OK", "template catalog", f"{len(catalog)} valid templates"))
    seen = set()
    for entry in catalog:
        card = (entry.get("style") or {}).get("title_card")
        if not card or (card["font_family"], card["font_weight"]) in seen:
            continue
        seen.add((card["font_family"], card["font_weight"]))
        pattern = f"{card['font_family']}:weight={WEIGHTS[card['font_weight']][0]}"
        resolved = _output(["fc-match", "-f", "%{family[0]}", pattern]).strip()
        exact = resolved.lower() == card["font_family"].lower()
        rows.append(("OK" if exact else "WARN", f"font {card['font_family']} {card['font_weight']}",
                     resolved if exact else f"substituted by {resolved!r}; install the font for "
                     "on-brand output"))
    return rows
