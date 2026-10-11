"""Extension points: providers, renderers, analyzers and exporters.

Every stage of a pipeline is a plugin *type* looked up by name. Built-in types
ship with VideoGenome; third-party packages add their own through Python entry
points, with no changes to this repository:

    [project.entry-points."videogenome.providers"]
    my-tts = "my_package.tts:MyTTSProvider"

A pipeline profile (see videogenome.profile) then instantiates named plugin
instances from these types with operator-owned configuration. Job manifests
never choose plugins, endpoints, commands or secrets.
"""
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from videogenome.compiler import ProductionError


class PluginError(ProductionError):
    """A plugin is missing, misconfigured, or cannot honour a request."""


# --------------------------------------------------------------------------
# Capabilities: the typed request contract every provider of a kind accepts.
# The set is open: plugins may register new capabilities. Free-text fields may
# carry untrusted job copy; adapters must never place them where they could be
# interpreted as code, options or URLs.
#
# Every request may also carry two fields filled by the producer:
#   media      - "audio" | "image" | "video": the kind of file expected back
#   references - {input_name: absolute path} of job assets the blueprint
#                passes along (e.g. a product .glb, a reference photo)

FREE_TEXT_FIELDS = frozenset({"text", "prompt", "negative_prompt", "direction", "filename", "query"})
COMMON_FIELDS = {"media": "string", "references": "object"}

CAPABILITIES: dict[str, dict] = {
    "speech": {
        "media": ["audio"],
        "description": "Synthesise spoken audio from text",
        "required": ["text"],
        "fields": {"text": "string", "direction": "string", "voice": "string",
                   "language": "string", "speed": "number", "seed": "integer",
                   "max_seconds": "number"},
    },
    "voice_conversion": {
        "media": ["audio"],
        "description": "Re-voice references.source with a target voice (identity transfer)",
        "required": [],
        "fields": {"voice": "string", "seed": "integer"},
    },
    "music": {
        "media": ["audio"],
        "description": "Compose instrumental music or a bed from a prompt",
        "required": ["prompt", "duration_seconds"],
        "fields": {"prompt": "string", "negative_prompt": "string", "query": "string",
                   "duration_seconds": "number", "seed": "integer", "style": "string"},
    },
    "sound": {
        "media": ["audio"],
        "description": "Generate a sound effect or ambience from a prompt",
        "required": ["prompt", "duration_seconds"],
        "fields": {"prompt": "string", "negative_prompt": "string", "query": "string",
                   "duration_seconds": "number", "seed": "integer", "style": "string"},
    },
    "image": {
        "media": ["image"],
        "description": "Generate a still image from a prompt",
        "required": ["prompt", "width", "height"],
        "fields": {"prompt": "string", "negative_prompt": "string", "query": "string", "width": "integer",
                   "height": "integer", "seed": "integer", "style": "string"},
    },
    "video": {
        "media": ["video"],
        "description": "Generate or render a video clip (text/image-to-video, 3D, procedural)",
        "required": ["prompt", "width", "height", "fps", "duration_seconds"],
        "fields": {"prompt": "string", "negative_prompt": "string", "query": "string", "width": "integer",
                   "height": "integer", "fps": "integer", "duration_seconds": "number",
                   "seed": "integer", "style": "string"},
    },
    "typing": {
        "media": ["video"],
        "description": "Animate text or code being typed (terminal, editor, document)",
        "required": ["text", "width", "height", "fps", "duration_seconds"],
        "fields": {"text": "string", "filename": "string", "language": "string", "style": "string",
                   "width": "integer", "height": "integer", "fps": "integer",
                   "duration_seconds": "number", "seed": "integer"},
    },
    "procedural": {
        "media": ["audio", "image", "video"],
        "description": "Render a procedural recipe (code + typed params) from the recipe catalog",
        "required": ["recipe"],
        "fields": {"recipe": "string", "preset": "string", "params": "object", "width": "integer",
                   "height": "integer", "fps": "integer", "duration_seconds": "number", "seed": "integer"},
    },
    "render_3d": {
        "media": ["image", "video"],
        "description": "Render a 3D scene, model or product (still or animation)",
        "required": ["width", "height"],
        "fields": {"prompt": "string", "style": "string", "width": "integer",
                   "height": "integer", "fps": "integer", "duration_seconds": "number",
                   "seed": "integer"},
    },
}


def register_capability(name: str, spec: dict) -> None:
    """Add a capability contract (``media``, ``description``, ``required``, ``fields``)."""
    if not isinstance(name, str) or not name.replace("_", "").isalnum() or not name[:1].isalpha():
        raise PluginError(f"Invalid capability name {name!r}")
    media = set(spec.get("media", []))
    if not media or not media <= {"audio", "image", "video"}:
        raise PluginError(f"Capability {name!r} must declare media among audio/image/video")
    fields = spec.get("fields", {})
    if any(kind not in ("string", "number", "integer") for kind in fields.values()):
        raise PluginError(f"Capability {name!r} fields must be string, number or integer")
    if not set(spec.get("required", [])) <= set(fields):
        raise PluginError(f"Capability {name!r} requires undeclared fields")
    existing = CAPABILITIES.get(name)
    if existing and existing != spec:
        raise PluginError(f"Capability {name!r} is already defined differently")
    CAPABILITIES[name] = spec

_JSON_TYPES = {"string": str, "number": (int, float), "integer": int, "object": dict}


def check_request(capability: str, request: dict) -> None:
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise PluginError(f"Unknown capability {capability!r}; known: {sorted(CAPABILITIES)}")
    fields = {**spec["fields"], **COMMON_FIELDS}
    unknown = sorted(set(request) - set(fields))
    if unknown:
        raise PluginError(f"{capability} request has unknown fields {unknown}")
    for name in spec["required"]:
        if request.get(name) in (None, ""):
            raise PluginError(f"{capability} request requires {name!r}")
    if "media" in request and request["media"] not in spec["media"]:
        raise PluginError(f"{capability} cannot produce {request['media']} (only {spec['media']})")
    references = request.get("references", {})
    if not isinstance(references, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in references.items()):
        raise PluginError(f"{capability} references must map names to paths")
    for name, value in request.items():
        if name in COMMON_FIELDS:
            continue
        expected = _JSON_TYPES[fields[name]]
        if isinstance(value, bool) or not isinstance(value, expected):
            raise PluginError(f"{capability} field {name!r} must be {spec['fields'][name]}")
        if isinstance(value, str) and "\x00" in value:
            raise PluginError(f"{capability} field {name!r} contains a NUL byte")


# --------------------------------------------------------------------------
# Interfaces


class Plugin(ABC):
    """Common shape: a named instance with validated, operator-owned config."""

    #: JSON Schema for this type's ``config`` block (validated on load).
    config_schema: dict = {"type": "object"}
    #: One-line summary shown by ``videogenome plugins``.
    summary: str = ""

    def __init__(self, name: str, config: dict, *, base_dir: Path | None = None) -> None:
        errors = sorted(Draft202012Validator(self.config_schema).iter_errors(config),
                        key=lambda e: list(e.absolute_path))
        if errors:
            details = "; ".join(f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
                                for e in errors[:6])
            raise PluginError(f"Invalid config for {type(self).__name__} {name!r}: {details}")
        self.name = name
        self.config = config
        self.base_dir = base_dir or Path.cwd()

    def check(self) -> list[tuple[str, str]]:
        """Readiness rows ``(OK|WARN|FAIL, detail)`` for ``videogenome doctor``."""
        return []

    def describe(self) -> dict:
        return {"name": self.name, "type": type(self).__name__}


@dataclass
class Generated:
    """A provider's output file plus facts it can vouch for."""
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class Provider(Plugin):
    """Produces one media file for a capability request."""

    #: Capabilities this *type* can serve; instances may narrow it in config.
    #: Generic adapters (command, mcp, comfyui...) declare ``{"*"}``: any
    #: capability the operator lists in the instance's config.
    capabilities: frozenset[str] = frozenset()
    #: Capability contracts this type introduces (registered when loaded).
    capability_specs: dict[str, dict] = {}
    #: True when generate() reports per-item ``rights`` in its metadata (e.g. a
    #: CC0 search result or an MIT recipe) instead of relying on output_rights.
    reports_rights: bool = False

    def serves(self) -> frozenset[str]:
        declared = frozenset(self.config.get("capabilities", []))
        if "*" in self.capabilities:
            return declared
        return declared & self.capabilities if declared else self.capabilities

    @abstractmethod
    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        """Write the result inside ``workdir`` and return it. Never fake output."""

    def describe(self) -> dict:
        model = self.config.get("model", {})
        return {**super().describe(), "capabilities": sorted(self.serves()), "model": model}


class Renderer(Plugin):
    """Assembles a compiled plan into a finished programme file."""

    @abstractmethod
    def unsupported(self, plan: dict) -> list[str]:
        """Features in ``plan`` this renderer cannot honour (refuse, don't fake)."""

    @abstractmethod
    def render(self, plan: dict, job_directory: Path, output: Path) -> dict:
        """Render and verify; return a report merged into the receipt."""


class Analyzer(Plugin):
    """Measures a finished programme; metrics feed machine-checked gates."""

    #: Metric names this analyzer may report.
    metrics: frozenset[str] = frozenset()

    @abstractmethod
    def measure(self, output: Path, plan: dict) -> dict:
        """Return ``{"metrics": {...}, "not_applicable": {metric: reason}, "details": {...}}``."""


class Exporter(Plugin):
    """Writes review or distribution sidecars next to the programme."""

    @abstractmethod
    def export(self, plan: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        """Return ``{kind: path}`` for every file written."""


# --------------------------------------------------------------------------
# Registry

KINDS: dict[str, tuple[str, type[Plugin]]] = {
    "provider": ("videogenome.providers", Provider),
    "renderer": ("videogenome.renderers", Renderer),
    "analyzer": ("videogenome.analyzers", Analyzer),
    "exporter": ("videogenome.exporters", Exporter),
}

BUILTINS: dict[str, dict[str, str]] = {
    "provider": {
        "command": "videogenome.providers.command:CommandProvider",
        "openai-compatible": "videogenome.providers.openai_compatible:OpenAICompatibleProvider",
        "comfyui": "videogenome.providers.comfyui:ComfyUIProvider",
        "mcp": "videogenome.providers.mcp:MCPProvider",
        "procedural": "videogenome.providers.procedural:ProceduralProvider",
        "openverse": "videogenome.providers.stock:OpenverseProvider",
        "wikimedia-commons": "videogenome.providers.stock:WikimediaCommonsProvider",
        "placeholder": "videogenome.providers.placeholder:PlaceholderProvider",
    },
    "renderer": {"ffmpeg": "videogenome.render:FFmpegRenderer"},
    "analyzer": {"ffmpeg": "videogenome.qa:FFmpegAnalyzer"},
    "exporter": {
        "subtitles": "videogenome.deliverables:SubtitleExporter",
        "poster": "videogenome.deliverables:PosterExporter",
        "contact_sheet": "videogenome.deliverables:ContactSheetExporter",
    },
}

_REGISTERED: dict[str, dict[str, type[Plugin]]] = {kind: {} for kind in KINDS}


def register(kind: str, type_name: str, cls: type[Plugin]) -> None:
    """Register a plugin type in-process (tests, notebooks, embedding apps)."""
    if kind not in KINDS:
        raise PluginError(f"Unknown plugin kind {kind!r}")
    if not issubclass(cls, KINDS[kind][1]):
        raise PluginError(f"{cls.__name__} does not implement {KINDS[kind][1].__name__}")
    _REGISTERED[kind][type_name] = cls


def unregister(kind: str, type_name: str) -> None:
    _REGISTERED[kind].pop(type_name, None)


def _import(spec: str) -> Any:
    module, _, attribute = spec.partition(":")
    return getattr(importlib.import_module(module), attribute)


def available(kind: str) -> dict[str, str]:
    """Plugin type names for ``kind`` mapped to where they come from."""
    group = KINDS[kind][0]
    found = {name: f"builtin ({spec})" for name, spec in BUILTINS[kind].items()}
    for entry in entry_points(group=group):
        found.setdefault(entry.name, f"entry point ({entry.value})")
    for name, cls in _REGISTERED[kind].items():
        found[name] = f"registered ({cls.__module__}.{cls.__qualname__})"
    return dict(sorted(found.items()))


def load_type(kind: str, type_name: str) -> type[Plugin]:
    if kind not in KINDS:
        raise PluginError(f"Unknown plugin kind {kind!r}")
    group, base = KINDS[kind]
    if type_name in _REGISTERED[kind]:
        cls = _REGISTERED[kind][type_name]
    elif type_name in BUILTINS[kind]:
        cls = _import(BUILTINS[kind][type_name])
    else:
        matches = [e for e in entry_points(group=group) if e.name == type_name]
        if not matches:
            raise PluginError(f"No {kind} plugin type {type_name!r}; available: "
                              f"{', '.join(available(kind)) or 'none'}")
        try:
            cls = matches[0].load()
        except Exception as exc:  # noqa: BLE001 - third-party import failure
            raise PluginError(f"Cannot load {kind} plugin {type_name!r}: {exc}") from exc
    if not (isinstance(cls, type) and issubclass(cls, base)):
        raise PluginError(f"{kind} plugin {type_name!r} does not implement {base.__name__}")
    for capability, spec in getattr(cls, "capability_specs", {}).items():
        register_capability(capability, spec)
    return cls


def instantiate(kind: str, name: str, spec: dict, *, base_dir: Path) -> Plugin:
    cls = load_type(kind, spec["type"])
    return cls(name, spec.get("config", {}), base_dir=base_dir)
