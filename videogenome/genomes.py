"""The genome library: every class of video, labelled by how ready it is.

A genome is one class of video (kinetic typography, a data story, a 3D product
hero...). Each lives in ``genomes/<id>/`` with a manifest and an authoring
prompt, and points at the code and templates that implement it. Its **level**
is derived from what actually exists, never declared:

* ``template`` - at least one ready-to-fill template: give a brief, get a video;
* ``code``     - recipes render it, but no template locks it yet: set params;
* ``prompt``   - only the authoring prompt: hand it to a frontier model to write
  the code, preview it with ``videogenome capture``, then promote it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from videogenome.compiler import ProductionError
from videogenome.resources import DATA_ROOT, SCHEMAS

GENOME_SCHEMA = SCHEMAS / "genome.schema.json"
BUILTIN_GENOMES = DATA_ROOT / "genomes"
GENOME_PATH_ENV = "VIDEOGENOME_GENOME_PATH"
LEVELS = ("template", "code", "prompt")


@dataclass(frozen=True)
class Genome:
    data: dict
    directory: Path

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def prompt_path(self) -> Path:
        return self.directory / self.data["prompt"]

    def prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")

    def level(self) -> str:
        if self.data.get("templates"):
            return "template"
        if self.data.get("recipes"):
            return "code"
        return "prompt"

    def describe(self) -> dict:
        return {**{k: v for k, v in self.data.items() if k != "genome_schema"}, "level": self.level(),
                "prompt_path": str(self.prompt_path)}


def genome_roots(extra: Iterable[Path] = ()) -> list[Path]:
    candidates = [BUILTIN_GENOMES, *(Path(p) for p in os.environ.get(GENOME_PATH_ENV, "").split(os.pathsep) if p),
                  *map(Path, extra)]
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def genome_errors(data: object, directory: Path, *, check_links: bool = True,
                  template_dirs: Iterable[Path] = ()) -> list[str]:
    schema = json.loads(GENOME_SCHEMA.read_text(encoding="utf-8"))
    errors = [f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
              for e in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))]
    if errors:
        return errors
    assert isinstance(data, dict)
    if directory.name != data["id"]:
        errors.append(f"directory {directory.name!r} must match id {data['id']!r}")
    prompt = directory / data["prompt"]
    if not prompt.is_file():
        errors.append(f"prompt {data['prompt']} does not exist")
    elif len(prompt.read_text(encoding="utf-8").split()) < 120:
        errors.append(f"prompt {data['prompt']} is too short to brief a model (under 120 words)")
    if check_links:
        try:
            known_recipes, known_templates = _known_links(tuple(map(str, template_dirs)))
        except ProductionError as exc:  # Another file is broken; say so instead of crashing.
            return errors + [f"cannot check links while the library is invalid: {exc}"]
        errors += [f"unknown recipe {r!r}" for r in data.get("recipes", []) if r not in known_recipes]
        errors += [f"unknown template {t!r}" for t in data.get("templates", []) if t not in known_templates]
        if "any" not in data["formats"]:  # The library filters by format: list every one a template renders.
            rendered = set().union(*(known_templates.get(t, set()) for t in data.get("templates", [])))
            if missing := sorted(rendered - set(data["formats"])):
                errors.append(f"formats must include {missing}, which its templates render")
    return errors


_LINKS: dict[tuple, tuple[set, set]] = {}


def _known_links(template_dirs: tuple[str, ...]) -> tuple[set, dict[str, set]]:
    """Recipe ids and template ids with their formats, discovered once per process."""
    if template_dirs not in _LINKS:
        from videogenome.catalog import discover as templates
        from videogenome.procedural import catalog as recipes
        _LINKS[template_dirs] = (set(recipes.discover()),
                                 {entry["id"]: {f["aspect_ratio"] for f in entry["formats"]}
                                  for entry in templates(template_dirs=map(Path, template_dirs))})
    return _LINKS[template_dirs]


def discover(extra: Iterable[Path] = (), *, template_dirs: Iterable[Path] = ()) -> dict[str, Genome]:
    found: dict[str, Genome] = {}
    for root in genome_roots(extra):
        for manifest in sorted(root.glob("*/genome.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProductionError(f"Cannot read {manifest}: {exc}") from exc
            problems = genome_errors(data, manifest.parent, check_links=False)
            if problems:
                raise ProductionError(f"Invalid genome {manifest}: {'; '.join(problems)}")
            if data["id"] in found:
                raise ProductionError(f"Genome id {data['id']!r} is defined more than once")
            found[data["id"]] = Genome(data, manifest.parent)
    return found


def get(genome_id: str, extra: Iterable[Path] = ()) -> Genome:
    genomes = discover(extra)
    if genome_id not in genomes:
        raise ProductionError(f"Unknown genome {genome_id!r}; run `videogenome library`")
    return genomes[genome_id]


def library(extra: Iterable[Path] = (), *, level: str | None = None, family: str | None = None) -> list[dict]:
    order = {name: index for index, name in enumerate(LEVELS)}
    rows = [g.describe() for g in discover(extra).values()
            if (not level or g.level() == level) and (not family or g.data["family"] == family)]
    return sorted(rows, key=lambda row: (order[row["level"]], row["family"], row["id"]))
