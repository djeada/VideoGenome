"""Pipeline profiles: which plugins produce, render, measure and export.

A profile is operator configuration (a JSON file), selected with
``--pipeline ID|PATH`` or ``VIDEOGENOME_PIPELINE``. Blueprints declare *what*
is needed (capability + request template + roles); profiles decide *who*
does it. Jobs can choose neither.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from videogenome.plugins import (
    Analyzer, Exporter, Plugin, PluginError, Provider, Renderer, Writer, instantiate,
)
from videogenome.providers.base import expand_env
from videogenome.resources import DATA_ROOT, SCHEMAS

PIPELINE_SCHEMA = SCHEMAS / "pipeline.schema.json"
BUILTIN_PIPELINES = DATA_ROOT / "pipelines"
PIPELINE_ENV = "VIDEOGENOME_PIPELINE"
PIPELINE_PATH_ENV = "VIDEOGENOME_PIPELINE_PATH"

DEFAULT = {
    "pipeline_schema": "0.1.0", "id": "default",
    "description": "Procedural recipes, FFmpeg rendering, measurement and sidecars.",
    "verification": "CI",
    "providers": {"procedural": {"type": "procedural"}},
    "routes": {"procedural": "procedural"},
    "renderer": {"type": "ffmpeg"},
    "analyzers": [{"type": "ffmpeg"}],
    "exporters": [{"type": "subtitles"}, {"type": "poster"}, {"type": "contact_sheet"}, {"type": "review"}],
}


def pipeline_roots(extra: Iterable[Path] = ()) -> list[Path]:
    candidates = [BUILTIN_PIPELINES, *(Path(p) for p in os.environ.get(PIPELINE_PATH_ENV, "")
                                       .split(os.pathsep) if p), *map(Path, extra)]
    return [c.resolve() for c in candidates if c.is_dir()]


def _find(reference: str, extra: Iterable[Path]) -> Path:
    path = Path(reference).expanduser()
    if path.suffix == ".json" or os.sep in reference:
        if not path.is_file():
            raise PluginError(f"Pipeline profile not found: {reference}")
        return path.resolve()
    matches = []
    for root in pipeline_roots(extra):
        for candidate in sorted(root.glob("**/*.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("pipeline_schema") and data.get("id") == reference:
                matches.append(candidate.resolve())
    if not matches:
        raise PluginError(f"Unknown pipeline {reference!r}; see `videogenome pipelines`")
    if len(set(matches)) > 1:
        raise PluginError(f"Pipeline id {reference!r} is defined more than once: {matches}")
    return matches[0]


def discover_pipelines(extra: Iterable[Path] = ()) -> list[dict]:
    found = []
    for root in pipeline_roots(extra):
        for candidate in sorted(root.glob("**/*.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("pipeline_schema"):
                found.append({"id": data.get("id"), "description": data.get("description"),
                              "verification": data.get("verification"),
                              "routes": sorted(data.get("routes", {})),
                              "writer": (data.get("writer") or {}).get("type"), "path": str(candidate)})
    return found


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"Cannot read pipeline profile {path}: {exc}") from exc
    schema = json.loads(PIPELINE_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(f"/{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:8])
        raise PluginError(f"Invalid pipeline profile {path}: {details}")
    return data


class Profile:
    def __init__(self, data: dict, sources: list[tuple[Path | None, dict]]) -> None:
        self.data = data
        self.sources = sources
        self._instances: dict[tuple[str, str], Plugin] = {}

    # ---- loading ----------------------------------------------------------
    @classmethod
    def load(cls, reference: str | Path | None = None, *, search: Iterable[Path] = ()) -> "Profile":
        search = list(search)
        reference = reference or os.environ.get(PIPELINE_ENV)
        if not reference:
            return cls(dict(DEFAULT), [(None, DEFAULT)])
        chain: list[tuple[Path | None, dict]] = []
        seen: set[Path] = set()
        current: str | None = str(reference)
        while current:
            path = _find(current, search)
            if path in seen:
                raise PluginError(f"Pipeline profiles extend each other in a cycle at {path}")
            seen.add(path)
            data = _read(path)
            chain.append((path, data))
            current = data.get("extends")
        merged = dict(DEFAULT)
        for path, data in reversed(chain):
            base_dir = str(path.parent)
            for key in ("providers", "routes", "voices", "styles"):
                entries = data.get(key, {})
                if key == "providers":  # Remember each provider's own directory.
                    entries = {n: {**spec, "_base_dir": base_dir} for n, spec in entries.items()}
                merged[key] = {**merged.get(key, {}), **entries}
            for key in ("renderer", "analyzers", "exporters"):
                if key in data:
                    merged[key] = data[key]
            if "writer" in data:  # Resolved relative to the profile that declares it.
                merged["writer"] = {**data["writer"], "_base_dir": base_dir}
            for key in ("id", "description", "verification"):
                merged[key] = data[key]
        return cls(merged, chain)

    # ---- plugin access -----------------------------------------------------
    def _plugin(self, kind: str, name: str, spec: dict, base_dir: Path) -> Plugin:
        key = (kind, name)
        if key not in self._instances:
            clean = {k: v for k, v in spec.items() if k != "_base_dir"}
            clean["config"] = expand_env(clean.get("config", {}))
            self._instances[key] = instantiate(kind, name, clean, base_dir=base_dir)
        return self._instances[key]

    def provider(self, name: str) -> Provider:
        spec = self.data.get("providers", {}).get(name)
        if spec is None:
            raise PluginError(f"Pipeline {self.id!r} has no provider named {name!r}")
        plugin = self._plugin("provider", name, spec, Path(spec.get("_base_dir", ".")))
        assert isinstance(plugin, Provider)
        return plugin

    def routes_for(self, capability: str) -> list[list[tuple[str, str]]]:
        """Alternatives (fallback order), each a chain of (provider, capability)."""
        route = self.data.get("routes", {}).get(capability)
        if route is None:
            return []
        if isinstance(route, str):
            return [[(route, capability)]]
        if "fallback" in route:
            return [[(name, capability)] for name in route["fallback"]]
        return [[(step["provider"], step.get("capability", capability)) for step in route["chain"]]]

    def role(self, table: str, name: str | None) -> str | None:
        values = self.data.get(table, {})
        if name is None:
            value = values.get("default")
        else:
            value = values.get(name, values.get("default"))
        return expand_env(value) if value is not None else None

    def renderer(self) -> Renderer:
        plugin = self._plugin("renderer", "renderer", self.data["renderer"], self.base_dir)
        assert isinstance(plugin, Renderer)
        return plugin

    def analyzers(self) -> list[Analyzer]:
        return [self._plugin("analyzer", f"analyzer{i}", spec, self.base_dir)  # type: ignore[misc]
                for i, spec in enumerate(self.data.get("analyzers", []))]

    def writer(self) -> Writer:
        spec = self.data.get("writer")
        if spec is None:
            raise PluginError(f"Pipeline {self.id!r} has no writer; choose a profile with one "
                              "(see `videogenome pipelines`) or fill the job's text inputs yourself")
        plugin = self._plugin("writer", "writer", spec, Path(spec.get("_base_dir", ".")))
        assert isinstance(plugin, Writer)
        return plugin

    def exporters(self) -> list[Exporter]:
        return [self._plugin("exporter", f"exporter{i}", spec, self.base_dir)  # type: ignore[misc]
                for i, spec in enumerate(self.data.get("exporters", []))]

    # ---- reporting ----------------------------------------------------------
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def base_dir(self) -> Path:
        path = self.sources[0][0]
        return path.parent if path else Path.cwd()

    def describe(self) -> dict:
        return {
            "id": self.id, "verification": self.data["verification"],
            "sources": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p, _ in self.sources if p],
            "renderer": self.data["renderer"]["type"],
            "analyzers": [a["type"] for a in self.data.get("analyzers", [])],
            "exporters": [e["type"] for e in self.data.get("exporters", [])],
            "routes": self.data.get("routes", {}),
            **({"writer": self.data["writer"]["type"]} if "writer" in self.data else {}),
        }

    def check(self) -> list[tuple[str, str, str]]:
        rows = []
        for name in self.data.get("providers", {}):
            label = f"provider {name}"
            try:
                provider = self.provider(name)
            except PluginError as exc:
                rows.append(("FAIL", label, str(exc)))
                continue
            results = provider.check() or [("OK", f"{type(provider).__name__} loaded")]
            rows += [(status, label, detail) for status, detail in results]
            if (not provider.config.get("output_rights") and not provider.reports_rights
                    and not isinstance(provider, _placeholder_type())):
                rows.append(("WARN", label, "no output_rights declared: produce will refuse its media"))
        for capability in self.data.get("routes", {}):
            for chain in self.routes_for(capability):
                for provider_name, step_capability in chain:
                    if provider_name not in self.data.get("providers", {}):
                        rows.append(("FAIL", f"route {capability}", f"unknown provider {provider_name!r}"))
        if "writer" in self.data:
            try:
                writer = self.writer()
                rows += [(status, "writer", detail)
                         for status, detail in (writer.check() or [("OK", f"{type(writer).__name__} loaded")])]
            except PluginError as exc:
                rows.append(("FAIL", "writer", str(exc)))
        for kind, plugins in (("renderer", [self.data["renderer"]]),
                              ("analyzer", self.data.get("analyzers", [])),
                              ("exporter", self.data.get("exporters", []))):
            for spec in plugins:
                try:
                    from videogenome.plugins import load_type
                    load_type(kind, spec["type"])
                    rows.append(("OK", f"{kind} {spec['type']}", "loaded"))
                except PluginError as exc:
                    rows.append(("FAIL", f"{kind} {spec['type']}", str(exc)))
        return rows


def _placeholder_type() -> type:
    from videogenome.providers.placeholder import PlaceholderProvider
    return PlaceholderProvider
