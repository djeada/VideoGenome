"""MCP server: connect any agent (Claude Code, Cursor, an Agent SDK app) to VideoGenome.

    videogenome mcp --pipeline procedural --workspace ~/videogenome-runs

The agent browses the library, reads a template's slot contracts, writes the
copy itself (it *is* the writer), checks it with the same validator `fill`
uses, and renders through the operator's pipeline. It can also hand over HTML
it wrote and get a frame-exact video back, unchanged. Contact sheets come back
as images so a vision-capable agent can judge its own output.

The operator fixes the pipeline and workspace when starting the server; no tool
accepts a pipeline, provider, command, endpoint or file outside the workspace.
Protocol: JSON-RPC 2.0 over stdio (newline-delimited), MCP tools and prompts.
"""
from __future__ import annotations

import base64
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, TextIO

from videogenome import __version__
from videogenome.compiler import ProductionError
from videogenome.service import Service

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """VideoGenome turns briefs into finished, measured videos from expert-locked templates.
Workflow: `library` (what can be made, by readiness) -> `template` (slot contracts and examples) ->
write copy for the slots yourself -> `check_inputs` (fix every issue it reports; pass the brief so
names, quotes and numbers are matched against it) -> `render` -> look at the returned contact sheet.
Never invent names, quotes, testimonials, numbers or dates: slots marked VERBATIM must use the
brief's exact words. To render code you wrote, call `capture_html` with a self-contained page that
animates with requestAnimationFrame/CSS/timers (it runs unmodified on a virtual clock; shared
libraries are at /_lib/vg-scene/vg-scene.js and /_lib/three/three.module.min.js).
Prompt-level classes come with authoring prompts (MCP prompts named author-<genome>)."""


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required or [],
                            "additionalProperties": False}}


TOOLS = [
    _tool("library", "List every class of video by readiness: template (give a brief, get a video), "
          "code (recipes with params) or prompt (authoring prompt only).",
          {"level": {"enum": ["template", "code", "prompt"]}, "family": {"type": "string"}}),
    _tool("genome", "Describe one class of video, including its authoring prompt.",
          {"id": {"type": "string"}}, ["id"]),
    _tool("templates", "List ready-to-fill templates with format, duration and whether text alone renders them.", {}),
    _tool("template", "Slot contracts for one template: every text slot, its limits (characters, spoken words, "
          "enum choices), whether it is VERBATIM, worked copy examples, media inputs and quality gates.",
          {"id": {"type": "string"}}, ["id"]),
    _tool("check_inputs", "Check proposed slot values exactly as the renderer will (copy fitting with the real "
          "font, caption limits, narration length, enums, verbatim grounding against the brief).",
          {"template": {"type": "string"}, "inputs": {"type": "object"},
           "brief": {"type": "string", "description": "The brief the copy answers; required to verify VERBATIM slots"}},
          ["template", "inputs"]),
    _tool("render", "Render a template from slot values you wrote: produces media with the operator's pipeline, "
          "renders, runs the gates and returns the video, review page, gate results and a contact sheet image.",
          {"template": {"type": "string"}, "inputs": {"type": "object"}, "brief": {"type": "string"},
           "name": {"type": "string", "description": "Short label for the run directory"}},
          ["template", "inputs"]),
    _tool("fill_from_brief", "Let the operator's configured writer model fill a template from a brief "
          "(only when the server's pipeline has a writer; otherwise write the copy yourself).",
          {"template": {"type": "string"}, "brief": {"type": "string"}}, ["template", "brief"]),
    _tool("recipes", "List code recipes (scenes, backgrounds, music, sound) with their parameter schemas and presets.",
          {"media": {"enum": ["video", "image", "audio"]}}),
    _tool("preview_recipe", "Render one recipe with a preset and parameter overrides; returns the file and a "
          "contact sheet image.",
          {"recipe": {"type": "string"}, "preset": {"type": "string"}, "params": {"type": "object"},
           "size": {"type": "string", "description": "WIDTHxHEIGHT, e.g. 1080x1920"},
           "duration": {"type": "number"}, "fps": {"type": "integer"}}, ["recipe"]),
    _tool("capture_html", "Render a self-contained HTML animation you wrote, unmodified, frame-exactly (virtual "
          "clock for rAF/performance.now/Date/timers/CSS/WAAPI; Web Audio is recorded in sync). Network is "
          "blocked; import shared libraries from /_lib/. Returns the video and a contact sheet image.",
          {"html": {"type": "string", "description": "Complete page source"},
           "size": {"type": "string"}, "fps": {"type": "integer"}, "duration": {"type": "number"},
           "click": {"type": "boolean", "description": "Click the centre once after load (click-to-play pages)"},
           "audio": {"type": "boolean"}, "params": {"type": "object", "description": "Exposed as window.vgSpec.params"},
           "name": {"type": "string"}}, ["html"]),
    _tool("runs", "List recent runs in the workspace with their outputs and gate results.",
          {"limit": {"type": "integer"}}),
]


class Server:
    def __init__(self, service: Service, out: TextIO = sys.stdout) -> None:
        self.service = service
        self.out = out
        self.handlers: dict[str, Callable[[dict], Any]] = {
            "library": lambda a: self.service.library(a.get("level"), a.get("family")),
            "genome": lambda a: self.service.genome(a["id"]),
            "templates": lambda a: self.service.templates(),
            "template": lambda a: self.service.template(a["id"]),
            "check_inputs": lambda a: self.service.check_inputs(a["template"], a["inputs"], a.get("brief")),
            "render": lambda a: self.service.render(a["template"], a["inputs"], brief=a.get("brief"),
                                                    author="agent (MCP)", name=a.get("name")),
            "fill_from_brief": lambda a: self.service.fill(a["template"], a["brief"]),
            "recipes": lambda a: self.service.recipes(a.get("media")),
            "preview_recipe": lambda a: self.service.preview_recipe(
                a["recipe"], preset=a.get("preset"), params=a.get("params"), size=a.get("size", "1280x720"),
                fps=int(a.get("fps", 30)), duration=float(a.get("duration", 6.0))),
            "capture_html": lambda a: self.service.capture(
                html=a["html"], size=a.get("size", "1920x1080"), fps=int(a.get("fps", 30)),
                duration=float(a.get("duration", 10.0)), click=bool(a.get("click")), audio=a.get("audio", True),
                params=a.get("params"), name=a.get("name", "agent-capture")),
            "runs": lambda a: self.service.workspace.runs(int(a.get("limit", 20))),
        }

    # ---- transport ----------------------------------------------------------------
    def send(self, message: dict) -> None:
        self.out.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.out.flush()

    def serve(self, stream: TextIO = sys.stdin) -> None:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            reply = self.handle(message)
            if reply is not None:
                self.send(reply)

    def handle(self, message: dict) -> dict | None:
        method, ident = message.get("method"), message.get("id")
        if ident is None:  # Notifications need no answer.
            return None
        try:
            result = self.dispatch(method, message.get("params") or {})
        except KeyError as exc:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": f"Missing {exc}"}}
        except LookupError as exc:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            return {"protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                    "serverInfo": {"name": "videogenome", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self.call(params["name"], params.get("arguments") or {})
        if method == "prompts/list":
            return {"prompts": [{"name": f"author-{row['id']}", "title": f"Author: {row['title']}",
                                 "description": f"[{row['level']}] {row['summary']}"}
                                for row in self.service.library()]}
        if method == "prompts/get":
            name = params["name"]
            if not name.startswith("author-"):
                raise LookupError(f"Unknown prompt {name!r}")
            genome = self.service.genome(name.removeprefix("author-"))
            return {"description": genome["summary"],
                    "messages": [{"role": "user", "content": {"type": "text", "text": genome["prompt_text"]}}]}
        if method in ("resources/list", "resources/templates/list"):
            return {"resources": []} if method == "resources/list" else {"resourceTemplates": []}
        raise LookupError(f"Method not found: {method}")

    def call(self, name: str, arguments: dict) -> dict:
        handler = self.handlers.get(name)
        if handler is None:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool {name!r}"}]}
        try:
            result = handler(arguments)
        except (ProductionError, KeyError, ValueError, TypeError) as exc:
            return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}
        except Exception as exc:  # noqa: BLE001 - report, never crash the session
            return {"isError": True, "content": [{"type": "text", "text": f"Internal error: {exc}\n"
                                                  + traceback.format_exc(limit=3)}]}
        content = [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False, default=str)}]
        sheet = result.get("contact_sheet") if isinstance(result, dict) else None
        if sheet and Path(sheet).is_file() and Path(sheet).stat().st_size < 4_000_000:
            content.append({"type": "image", "mimeType": "image/jpeg",
                            "data": base64.b64encode(Path(sheet).read_bytes()).decode()})
        return {"content": content, "isError": False}
