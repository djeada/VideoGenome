"""Locate bundled schemas and trusted template directories.

A source checkout keeps schemas/ and templates/ at the repository root; an
installed wheel bundles them under videogenome/_data. Additional template
directories are trusted only when the *operator* names them (CLI flag or the
VIDEOGENOME_TEMPLATE_PATH environment variable), never from job content.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

PACKAGE = Path(__file__).resolve().parent
_BUNDLED = PACKAGE / "_data"
DATA_ROOT = _BUNDLED if (_BUNDLED / "schemas").is_dir() else PACKAGE.parent
SCHEMAS = DATA_ROOT / "schemas"
BUILTIN_TEMPLATES = DATA_ROOT / "templates"
TEMPLATE_PATH_ENV = "VIDEOGENOME_TEMPLATE_PATH"


def template_roots(extra: Iterable[Path] = ()) -> list[Path]:
    """Built-in templates first, then environment and operator directories."""
    candidates = [BUILTIN_TEMPLATES]
    candidates += [Path(p) for p in os.environ.get(TEMPLATE_PATH_ENV, "").split(os.pathsep) if p]
    candidates += [Path(p) for p in extra]
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots
