"""Recipe discovery, validation and parameter resolution."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from videogenome.compiler import ProductionError
from videogenome.resources import DATA_ROOT, SCHEMAS

RECIPE_SCHEMA = SCHEMAS / "recipe.schema.json"
BUILTIN_RECIPES = DATA_ROOT / "recipes"
RECIPE_PATH_ENV = "VIDEOGENOME_RECIPE_PATH"
LIBRARY_DIR = "_lib"


def bundled_libraries() -> dict[str, Path]:
    """Shared browser libraries shipped with VideoGenome (served at /_lib/<name>/)."""
    base = BUILTIN_RECIPES / LIBRARY_DIR
    return {d.name: d for d in sorted(base.iterdir()) if d.is_dir()} if base.is_dir() else {}


def library_dir(root: Path, name: str) -> Path:
    """A shared browser library: the recipe tree's own ``_lib/<name>``, else the bundled one."""
    local = root / LIBRARY_DIR / name
    return local if local.is_dir() else BUILTIN_RECIPES / LIBRARY_DIR / name


@dataclass(frozen=True)
class Recipe:
    data: dict
    directory: Path

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def entry(self) -> Path:
        return self.directory / self.data["entry"]

    @property
    def root(self) -> Path:
        """The recipe tree this recipe belongs to (``<root>/<area>/<name>/``)."""
        return self.directory.parent.parent

    def libraries(self) -> list[Path]:
        return [library_dir(self.root, name) for name in self.data.get("libraries", [])]

    def sha256(self) -> str:
        """Hash of every file in the recipe directory and the shared libraries it uses."""
        digest = hashlib.sha256()
        bases = [("", self.directory)] + [(f"{LIBRARY_DIR}/{name}/", lib) for name, lib in
                                          zip(self.data.get("libraries", []), self.libraries())]
        for prefix, base in bases:  # Libraries may live in the bundled tree, outside this recipe's root.
            for path in sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
                digest.update((prefix + path.relative_to(base).as_posix()).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def resolve(self, preset: str | None = None, params: dict | None = None) -> dict:
        """Defaults <- preset <- explicit params, validated against the schema."""
        schema = self.data["params"]
        resolved = {name: copy.deepcopy(spec["default"]) for name, spec in schema["properties"].items()}
        if preset:
            presets = self.data.get("presets", {})
            if preset not in presets:
                raise ProductionError(f"Recipe {self.id} has no preset {preset!r}; "
                                      f"choose from {sorted(presets)}")
            resolved.update(copy.deepcopy(presets[preset]))
        resolved.update(params or {})
        errors = sorted(Draft202012Validator(schema).iter_errors(resolved), key=lambda e: list(e.absolute_path))
        if errors:
            details = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or 'params'}: {e.message}"
                                for e in errors[:6])
            raise ProductionError(f"Invalid params for recipe {self.id}: {details}")
        return resolved

    def describe(self) -> dict:
        props = self.data["params"]["properties"]
        return {
            "id": self.id, "version": self.data["version"], "title": self.data["title"],
            "description": self.data["description"], "media": self.data["media"],
            "runtime": self.data["runtime"], "tags": self.data.get("tags", []),
            "presets": sorted(self.data.get("presets", {})),
            "params": {name: {k: v for k, v in spec.items() if k != "$comment"} for name, spec in props.items()},
            "license": self.data["license"], "path": str(self.directory),
        }


def recipe_roots(extra: Iterable[Path] = ()) -> list[Path]:
    candidates = [BUILTIN_RECIPES, *(Path(p) for p in os.environ.get(RECIPE_PATH_ENV, "").split(os.pathsep) if p),
                  *map(Path, extra)]
    return [c.resolve() for c in candidates if c.is_dir()]


def recipe_errors(data: object, directory: Path) -> list[str]:
    schema = json.loads(RECIPE_SCHEMA.read_text(encoding="utf-8"))
    errors = [f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(data)]
    if errors:
        return errors
    assert isinstance(data, dict)
    params = data["params"]
    try:
        Draft202012Validator.check_schema(params)
    except Exception as exc:  # noqa: BLE001 - report any schema defect
        return [f"params is not a valid JSON Schema: {exc}"]
    validator = Draft202012Validator(params)
    defaults = {name: spec["default"] for name, spec in params["properties"].items()}
    errors += [f"defaults: {e.message}" for e in validator.iter_errors(defaults)]
    for name, preset in data.get("presets", {}).items():
        merged = {**defaults, **preset}
        errors += [f"preset {name}: {e.message}" for e in validator.iter_errors(merged)]
    if not (directory / data["entry"]).is_file():
        errors.append(f"entry {data['entry']} does not exist")
    if "timing" in data and data["runtime"] != "browser":
        errors.append("timing applies to browser recipes only")
    for name in data.get("libraries", []):
        if data["runtime"] != "browser":
            errors.append("libraries apply to browser recipes only")
        elif not library_dir(directory.parent.parent, name).is_dir():
            errors.append(f"library {name!r} not found in {directory.parent.parent / '_lib'}")
    return errors


_DISCOVERED: dict[tuple, dict[str, Recipe]] = {}


def discover(extra: Iterable[Path] = ()) -> dict[str, Recipe]:
    """All recipes, validated once per set of manifest files (cached on paths and mtimes)."""
    manifests = [m for root in recipe_roots(extra) for m in sorted(root.glob("**/recipe.json"))]
    key = tuple((str(m), m.stat().st_mtime_ns, m.stat().st_size) for m in manifests)
    if key not in _DISCOVERED:
        _DISCOVERED.clear()
        _DISCOVERED[key] = _discover(manifests)
    return dict(_DISCOVERED[key])


def _discover(manifests: list[Path]) -> dict[str, Recipe]:
    found: dict[str, Recipe] = {}
    for manifest in manifests:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        problems = recipe_errors(data, manifest.parent)
        if problems:
            raise ProductionError(f"Invalid recipe {manifest}: {'; '.join(problems)}")
        if data["id"] in found:
            raise ProductionError(f"Recipe id {data['id']!r} is defined more than once")
        found[data["id"]] = Recipe(data, manifest.parent)
    return found


def get(recipe_id: str, extra: Iterable[Path] = ()) -> Recipe:
    recipes = discover(extra)
    if recipe_id not in recipes:
        raise ProductionError(f"Unknown recipe {recipe_id!r}; run `videogenome recipes`")
    return recipes[recipe_id]
