"""Generic MCP adapter: drive any Model Context Protocol server's tools.

The operator names a stdio server command and a fixed sequence of tool calls
whose arguments are templates over the request, for example a Blender MCP
server's ``blender_python_exec`` with an operator-owned ``script_path`` and
``args``. Job text can fill argument *values*, but never an argument that is
code: free-text fields are refused in keys such as ``code`` or ``script``.
The final step must leave a file at ``{output}``.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from videogenome import __version__
from videogenome.plugins import FREE_TEXT_FIELDS, Generated, PluginError, Provider
from videogenome.providers.base import (
    EXTENSION_SCHEMA, fill, output_extension, provider_schema, template_fields, write_text_files,
)

PROTOCOL_VERSION = "2025-06-18"
CODE_KEYS = frozenset({"code", "script", "source", "command", "cmd", "python", "expression", "shell"})


def _free_text_in_code(arguments: Any, path: str = "") -> list[str]:
    found = []
    if isinstance(arguments, dict):
        for key, value in arguments.items():
            here = f"{path}.{key}" if path else key
            if key.lower() in CODE_KEYS and template_fields(value) & FREE_TEXT_FIELDS:
                found.append(here)
            found += _free_text_in_code(value, here)
    elif isinstance(arguments, list):
        for index, value in enumerate(arguments):
            found += _free_text_in_code(value, f"{path}[{index}]")
    return found


class _StdioSession:
    """Newline-delimited JSON-RPC 2.0 over a child process's stdin/stdout."""

    def __init__(self, argv: list[str], env: dict, cwd: Path, timeout: float, label: str) -> None:
        executable = sys.executable if argv[0] == "{python}" else argv[0]
        self.label, self.timeout = label, timeout
        try:
            self.process = subprocess.Popen(
                [executable, *argv[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=cwd, env={**os.environ, **env}, bufsize=1)
        except OSError as exc:
            raise PluginError(f"{label}: cannot start MCP server {argv[0]}: {exc}") from exc
        self.messages: queue.Queue = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: self.stderr.extend(self.process.stderr), daemon=True).start()
        self.next_id = 0

    def _read(self) -> None:
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue  # Servers may log to stdout; ignore non-protocol lines.
        self.messages.put(None)

    def _send(self, message: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise PluginError(f"{self.label}: MCP server closed: {''.join(self.stderr)[-600:]}") from exc

    def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        wanted = self.next_id
        self._send({"jsonrpc": "2.0", "id": wanted, "method": method, "params": params})
        while True:
            try:
                message = self.messages.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise PluginError(f"{self.label}: no response to {method} within {self.timeout:.0f}s") from exc
            if message is None:
                raise PluginError(f"{self.label}: MCP server exited: {''.join(self.stderr)[-800:]}")
            if "method" in message and "id" in message:  # Server-to-client request: decline.
                self._send({"jsonrpc": "2.0", "id": message["id"],
                            "error": {"code": -32601, "message": "not supported by videogenome"}})
                continue
            if message.get("id") != wanted:
                continue
            if "error" in message:
                raise PluginError(f"{self.label}: {method} failed: {json.dumps(message['error'])[:600]}")
            return message.get("result", {})

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


class MCPProvider(Provider):
    summary = "Call tools on a stdio MCP server (e.g. Blender, ParaView) to produce {output}"
    capabilities = frozenset({"*"})
    config_schema = provider_schema({
        "server": {
            "type": "object", "additionalProperties": False, "required": ["argv"],
            "properties": {"argv": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                           "env": {"type": "object", "additionalProperties": {"type": "string"}},
                           "cwd": {"type": "string"}},
        },
        "steps": {
            "type": "array", "minItems": 1,
            "items": {"type": "object", "additionalProperties": False, "required": ["tool"],
                      "properties": {"tool": {"type": "string", "minLength": 1},
                                     "arguments": {"type": "object"}}},
        },
        "extension": EXTENSION_SCHEMA,
        "defaults": {"type": "object"},
    }, required=["server", "steps", "extension", "capabilities"])

    def __init__(self, name: str, config: dict, **kwargs) -> None:
        super().__init__(name, config, **kwargs)
        for step in config["steps"]:
            unsafe = _free_text_in_code(step.get("arguments", {}))
            if unsafe:
                raise PluginError(f"MCP provider {name!r}: free text may not fill code arguments {unsafe}")
        if "{" in config["server"]["argv"][0] and config["server"]["argv"][0] != "{python}":
            raise PluginError(f"MCP provider {name!r}: the server executable must be fixed")

    def check(self) -> list[tuple[str, str]]:
        try:
            session = self._open(timeout=30)
        except PluginError as exc:
            return [("FAIL", str(exc))]
        try:
            tools = {tool["name"] for tool in session.request("tools/list", {}).get("tools", [])}
        except PluginError as exc:
            return [("FAIL", str(exc))]
        finally:
            session.close()
        missing = sorted({step["tool"] for step in self.config["steps"]} - tools)
        if missing:
            return [("FAIL", f"server lacks tools {missing}")]
        return [("OK", f"MCP server offers {len(tools)} tools including all {len(self.config['steps'])} steps")]

    def _open(self, *, timeout: float) -> _StdioSession:
        server = self.config["server"]
        values = {"profile_dir": str(self.base_dir), "python": sys.executable}
        cwd = Path(fill(server["cwd"], values)) if "cwd" in server else self.base_dir
        argv = [str(part) for part in fill(server["argv"], values)]
        env = {key: str(fill(value, values)) for key, value in server.get("env", {}).items()}
        session = _StdioSession(argv, env, cwd, timeout, f"MCP provider {self.name!r}")
        session.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": "videogenome", "version": __version__}})
        session.notify("notifications/initialized")
        return session

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        output = workdir / f"output{output_extension(self.config, request)}"
        values = {**self.config.get("defaults", {}), **request, **write_text_files(request, workdir),
                  "output": str(output), "workdir": str(workdir),
                  "profile_dir": str(self.base_dir), "capability": capability,
                  "python": sys.executable}
        session = self._open(timeout=self.config.get("timeout_seconds", 3600))
        transcript = []
        try:
            for step in self.config["steps"]:
                arguments = fill(step.get("arguments", {}), values)
                result = session.request("tools/call", {"name": step["tool"], "arguments": arguments})
                text = " ".join(part.get("text", "") for part in result.get("content", [])
                                if isinstance(part, dict))
                if result.get("isError"):
                    raise PluginError(f"MCP tool {step['tool']} failed: {text[:800]}")
                transcript.append({"tool": step["tool"], "result": text[:400]})
        finally:
            session.close()
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError(f"MCP provider {self.name!r}: tools finished but {output.name} was not written")
        return Generated(output, {"server": self.config["server"]["argv"][0], "steps": transcript})
