"""ComfyUI adapter: run an operator-exported API-format workflow per capability.

ComfyUI hosts most open-weight generators (FLUX, SDXL, SD3.5, Wan, LTX-Video,
HunyuanVideo, CogVideoX, Stable Audio Open, ACE-Step...). Export a workflow
with "Save (API)", then bind request fields to node inputs in the profile:

    "workflows": {"image": {
        "file": "${COMFY_WORKFLOWS}/flux_schnell.api.json",
        "bindings": {"prompt": [{"node": "6", "input": "text"}],
                     "seed": [{"node": "25", "input": "noise_seed"}]},
        "output_node": "9"}}

Frame counts for video models can be derived from duration with
``{"transform": "frames", "frame_multiple": 4, "frame_offset": 1}`` (4n+1).
"""
from __future__ import annotations

import copy
import json
import math
import time
import urllib.parse
import uuid
from pathlib import Path

from videogenome.plugins import Generated, PluginError, Provider
from videogenome.providers.base import http_json, provider_schema

BINDING = {
    "type": "object", "additionalProperties": False, "required": ["node", "input"],
    "properties": {
        "node": {"type": "string"}, "input": {"type": "string"},
        "transform": {"enum": ["frames"]},
        "frame_multiple": {"type": "integer", "minimum": 1},
        "frame_offset": {"type": "integer", "minimum": 0},
    },
}
OUTPUT_KEYS = ("images", "gifs", "videos", "audio", "files")


class ComfyUIProvider(Provider):
    summary = "Queue an exported ComfyUI API workflow with request fields bound to node inputs"
    capabilities = frozenset({"*"})
    config_schema = provider_schema({
        "base_url": {"type": "string", "pattern": "^https?://"},
        "poll_seconds": {"type": "number", "exclusiveMinimum": 0},
        "workflows": {
            "type": "object", "minProperties": 1,
            "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["file", "bindings"],
                "properties": {
                    "file": {"type": "string"},
                    "bindings": {"type": "object",
                                 "additionalProperties": {"type": "array", "items": BINDING}},
                    "output_node": {"type": "string"},
                },
            },
        },
    }, required=["base_url", "workflows"])

    def serves(self) -> frozenset[str]:
        return frozenset(self.config["workflows"])

    def _workflow(self, capability: str) -> tuple[dict, dict]:
        spec = self.config["workflows"].get(capability)
        if spec is None:
            raise PluginError(f"{self.name} has no workflow for {capability!r}")
        path = Path(spec["file"])
        path = path if path.is_absolute() else self.base_dir / path
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginError(f"{self.name}: cannot read workflow {path}: {exc}") from exc
        if not isinstance(workflow, dict) or not all(
                isinstance(node, dict) and "class_type" in node for node in workflow.values()):
            raise PluginError(f"{self.name}: {path.name} is not an API-format workflow (use Save (API))")
        return workflow, spec

    def check(self) -> list[tuple[str, str]]:
        rows = []
        for capability in self.config["workflows"]:
            try:
                self._workflow(capability)
                rows.append(("OK", f"{capability} workflow readable"))
            except PluginError as exc:
                rows.append(("FAIL", str(exc)))
        try:
            http_json("GET", self.config["base_url"].rstrip("/") + "/system_stats", timeout=5)
            rows.append(("OK", f"{self.config['base_url']} reachable"))
        except PluginError as exc:
            rows.append(("WARN", f"server not reachable now: {exc}"))
        return rows

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        template, spec = self._workflow(capability)
        workflow = copy.deepcopy(template)
        bound = {}
        for field, targets in spec["bindings"].items():
            if field not in request:
                continue  # Keep the workflow's own default.
            for target in targets:
                node = workflow.get(target["node"])
                if node is None:
                    raise PluginError(f"{self.name}: workflow has no node {target['node']!r}")
                value = request[field]
                if target.get("transform") == "frames":
                    multiple, offset = target.get("frame_multiple", 1), target.get("frame_offset", 0)
                    frames = math.ceil(request["duration_seconds"] * request["fps"])
                    value = math.ceil(max(0, frames - offset) / multiple) * multiple + offset
                node.setdefault("inputs", {})[target["input"]] = value
                bound[f"{target['node']}.{target['input']}"] = value
        base = self.config["base_url"].rstrip("/")
        queued = http_json("POST", f"{base}/prompt",
                           payload={"prompt": workflow, "client_id": uuid.uuid4().hex}, timeout=60)
        if queued.get("node_errors"):
            raise PluginError(f"{self.name}: workflow rejected: {json.dumps(queued['node_errors'])[:600]}")
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise PluginError(f"{self.name}: server did not return a prompt_id")
        deadline = time.monotonic() + self.config.get("timeout_seconds", 3600)
        while True:
            history = http_json("GET", f"{base}/history/{prompt_id}", timeout=60)
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise PluginError(f"{self.name}: execution failed: {json.dumps(status)[:600]}")
                if status.get("completed", True) and entry.get("outputs"):
                    break
            if time.monotonic() > deadline:
                raise PluginError(f"{self.name}: timed out waiting for prompt {prompt_id}")
            time.sleep(self.config.get("poll_seconds", 1.0))
        outputs = entry["outputs"]
        nodes = [spec["output_node"]] if "output_node" in spec else sorted(outputs)
        for node_id in nodes:
            for key in OUTPUT_KEYS:
                for item in outputs.get(node_id, {}).get(key, []):
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    query = urllib.parse.urlencode({"filename": item["filename"],
                                                    "subfolder": item.get("subfolder", ""),
                                                    "type": item.get("type", "output")})
                    data = http_json("GET", f"{base}/view?{query}", timeout=600, raw=True)
                    suffix = Path(item["filename"]).suffix.lower() or ".bin"
                    output = workdir / f"comfyui{suffix}"
                    output.write_bytes(data)
                    return Generated(output, {"prompt_id": prompt_id, "bound_inputs": bound,
                                              "workflow": spec["file"], "server_file": item["filename"]})
        raise PluginError(f"{self.name}: prompt {prompt_id} finished without a downloadable output")
