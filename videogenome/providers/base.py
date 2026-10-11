"""Shared provider plumbing: config fragments, templating, process and HTTP calls."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from videogenome.plugins import FREE_TEXT_FIELDS, PluginError

# {name}, {group.key}; a trailing "?" marks it optional ({references.model?}).
USER_AGENT = "VideoGenome (+https://github.com/djeada/VideoGenome)"
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?)(\??)\}")
MISSING = object()
EXTENSION = re.compile(r"^\.[a-z0-9]{1,8}$")

# Config every provider instance accepts, merged into each type's schema.
COMMON_PROPERTIES: dict[str, Any] = {
    "capabilities": {"type": "array", "items": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                     "uniqueItems": True},
    "model": {
        "type": "object", "additionalProperties": False,
        "properties": {"name": {"type": "string"}, "version": {"type": "string"},
                       "source": {"type": "string"}, "license": {"type": "string"}},
    },
    "output_rights": {
        "type": "object", "additionalProperties": False, "required": ["license", "evidence"],
        "properties": {"license": {"type": "string", "minLength": 1},
                       "evidence": {"type": "string", "minLength": 3}},
    },
    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400},
    # Ask for this much extra duration (tools whose length control is approximate).
    "duration_margin_seconds": {"type": "number", "minimum": 0, "maximum": 60},
    "notes": {"type": "string"},
}


def provider_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": required or [], "properties": {**COMMON_PROPERTIES, **properties}}


def template_fields(template: Any) -> set[str]:
    """Every ``{name}`` placeholder used anywhere inside a JSON-like template."""
    if isinstance(template, str):
        return {name for name, _ in PLACEHOLDER.findall(template.replace("{{", "").replace("}}", ""))}
    if isinstance(template, list):
        return set().union(*(template_fields(v) for v in template)) if template else set()
    if isinstance(template, dict):
        return set().union(*(template_fields(v) for v in template.values())) if template else set()
    return set()


def lookup(values: dict, name: str, optional: bool = False) -> Any:
    if "." in name:
        head, _, tail = name.partition(".")
        container = values.get(head)
        if not isinstance(container, dict) or tail not in container:
            if optional:
                return MISSING
            raise PluginError(f"Template needs {{{name}}} but the request has no {head}.{tail}")
        return container[tail]
    if name not in values or values[name] is None:
        if optional:
            return MISSING
        raise PluginError(f"Template needs {{{name}}} but the request does not provide it")
    return values[name]


def fill(template: Any, values: dict) -> Any:
    """Substitute placeholders. A string that is exactly ``{name}`` keeps the
    value's JSON type; embedded placeholders are stringified. ``{{``/``}}``
    escape literal braces. A missing optional whole placeholder becomes
    ``MISSING`` (dropped from objects, kept for argv post-processing)."""
    if isinstance(template, list):
        return [fill(item, values) for item in template]
    if isinstance(template, dict):
        filled = {key: fill(item, values) for key, item in template.items()}
        return {key: item for key, item in filled.items() if item is not MISSING}
    if not isinstance(template, str):
        return template
    whole = PLACEHOLDER.fullmatch(template)
    if whole:
        return lookup(values, whole.group(1), bool(whole.group(2)))
    parts = re.split(r"(\{\{|\}\})", template)
    out = []
    for part in parts:
        if part == "{{":
            out.append("{")
        elif part == "}}":
            out.append("}")
        else:
            def text(match: re.Match[str]) -> str:
                value = lookup(values, match.group(1), bool(match.group(2)))
                return "" if value is MISSING else str(value)
            out.append(PLACEHOLDER.sub(text, part))
    return "".join(out)


def check_argv_free_text(argv: list[str], label: str) -> None:
    """Free text may enter argv only as an option's value, never as a bare
    positional that a CLI could parse as a new option or a filename."""
    for index, element in enumerate(argv):
        used = template_fields(element) & FREE_TEXT_FIELDS
        if not used:
            continue
        whole = PLACEHOLDER.fullmatch(element)
        follows_flag = index > 0 and argv[index - 1].startswith("-") and not template_fields(argv[index - 1])
        prefixed = not whole and element.startswith("-") and "=" in element.split("{", 1)[0]
        if not ((whole and follows_flag) or prefixed):
            raise PluginError(
                f"{label}: free-text field(s) {sorted(used)} may only appear as an option value "
                "(\"--prompt\", \"{prompt}\" or \"--prompt={prompt}\"); prefer stdin or "
                "{text_file}/{prompt_file}"
            )


def drop_missing(argv: list) -> list[str]:
    """Remove missing optional arguments, and the option flag right before them."""
    result: list[str] = []
    for item in argv:
        if item is MISSING:
            if result and result[-1].startswith("-"):
                result.pop()
            continue
        result.append(str(item))
    return result


def output_extension(config: dict, request: dict) -> str:
    extension = config["extension"]
    if isinstance(extension, dict):
        media = request.get("media")
        if media not in extension:
            raise PluginError(f"No output extension configured for {media!r} media")
        return extension[media]
    return extension


EXTENSION_SCHEMA = {"oneOf": [
    {"type": "string", "pattern": EXTENSION.pattern},
    {"type": "object", "additionalProperties": False, "minProperties": 1,
     "properties": {media: {"type": "string", "pattern": EXTENSION.pattern}
                    for media in ("audio", "image", "video")}},
]}


def expand_env(value: Any) -> Any:
    """Expand ``${VAR}`` in operator-owned profile strings (never job data)."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise PluginError(f"Environment variable {name} is not set (needed by the pipeline profile)")
            return os.environ[name]
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def write_text_files(request: dict, workdir: Path) -> dict[str, str]:
    """Materialise free-text fields as files: ``{text_file}``, ``{prompt_file}``..."""
    files = {}
    for name in FREE_TEXT_FIELDS:
        if isinstance(request.get(name), str):
            path = workdir / f"{name}.txt"
            path.write_text(request[name], encoding="utf-8")
            files[f"{name}_file"] = str(path)
    return files


def run_process(argv: list[str], *, stdin: str | None, cwd: Path, env: dict[str, str],
                timeout: float, label: str) -> subprocess.CompletedProcess:
    executable = sys.executable if argv[0] == "{python}" else argv[0]
    try:
        completed = subprocess.run(
            [executable, *argv[1:]], input=stdin, capture_output=True, text=True,
            cwd=cwd, env={**os.environ, **env}, timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise PluginError(f"{label}: executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PluginError(f"{label}: timed out after {timeout:.0f}s") from exc
    if completed.returncode:
        raise PluginError(f"{label}: exited {completed.returncode}: {completed.stderr[-1200:]}")
    return completed


def http_json(method: str, url: str, *, payload: Any = None, headers: dict | None = None,
              timeout: float = 600, raw: bool = False) -> Any:
    """Minimal JSON-over-HTTP client (stdlib only); ``raw`` returns bytes."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise PluginError(f"Only http(s) endpoints are allowed: {url}")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": USER_AGENT,
        **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:600].decode("utf-8", "replace")
        raise PluginError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PluginError(f"{method} {url} failed: {exc}") from exc
    if raw:
        return body
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{method} {url} returned non-JSON content") from exc


def download(url: str, destination: Path, *, max_bytes: int, timeout: float = 300) -> Path:
    """Stream a public file to disk, refusing anything larger than ``max_bytes``."""
    if urllib.parse.urlparse(url).scheme != "https":
        raise PluginError(f"Refusing non-HTTPS download: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as out:  # noqa: S310
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > max_bytes:
                    raise PluginError(f"Download exceeds {max_bytes // (1 << 20)} MB: {url}")
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PluginError(f"Download failed: {url}: {exc}") from exc
    if total == 0:
        raise PluginError(f"Empty download: {url}")
    return destination


def api_headers(config: dict) -> dict[str, str]:
    name = config.get("api_key_env")
    if not name:
        return {}
    if not os.environ.get(name):
        raise PluginError(f"API key environment variable {name} is not set")
    return {"Authorization": f"Bearer {os.environ[name]}"}
