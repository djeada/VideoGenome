"""OpenAI-compatible HTTP adapter for self-hosted servers.

Many open-source servers speak this protocol: Kokoro-FastAPI, Speaches,
openedai-speech, LocalAI, vLLM-Omni and others. Only the speech
(``/audio/speech``) and image (``/images/generations``) endpoints are used.
The endpoint and any API key variable come from the operator's profile.
"""
from __future__ import annotations

import base64
from pathlib import Path

from videogenome.plugins import Generated, PluginError, Provider
from videogenome.providers.base import api_headers, http_json, provider_schema


class OpenAICompatibleProvider(Provider):
    summary = "POST to an OpenAI-compatible /audio/speech or /images/generations server"
    capabilities = frozenset({"speech", "image"})
    config_schema = provider_schema({
        "base_url": {"type": "string", "pattern": "^https?://"},
        "model_id": {"type": "string", "minLength": 1},
        "api_key_env": {"type": "string", "pattern": "^[A-Z_][A-Z0-9_]*$"},
        "response_format": {"enum": ["wav", "mp3", "flac", "opus", "aac", "pcm"]},
        "image_size": {"type": "string", "pattern": "^[0-9]+x[0-9]+$"},
        "extra": {"type": "object"},
    }, required=["base_url", "model_id"])

    def check(self) -> list[tuple[str, str]]:
        try:
            http_json("GET", self.config["base_url"].rstrip("/") + "/models",
                      headers=api_headers(self.config), timeout=5)
        except PluginError as exc:
            return [("WARN", f"server not reachable now: {exc}")]
        return [("OK", f"{self.config['base_url']} reachable")]

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        if capability not in self.serves():
            raise PluginError(f"{self.name} cannot serve {capability!r}")
        base = self.config["base_url"].rstrip("/")
        headers = api_headers(self.config)
        timeout = self.config.get("timeout_seconds", 600)
        extra = self.config.get("extra", {})
        if capability == "speech":
            fmt = self.config.get("response_format", "wav")
            # Delivery direction is sent as "instructions" only when the operator
            # opts in: servers that do not support it may reject the field.
            payload = {"model": self.config["model_id"], "input": request["text"],
                       "voice": request.get("voice", "default"), "response_format": fmt,
                       **({"speed": request["speed"]} if "speed" in request else {}),
                       **({"instructions": request["direction"]}
                          if "direction" in request and extra.get("allow_instructions") else {}),
                       **{k: v for k, v in extra.items() if k != "allow_instructions"}}
            body = http_json("POST", f"{base}/audio/speech", payload=payload, headers=headers,
                             timeout=timeout, raw=True)
            output = workdir / f"speech.{fmt}"
            output.write_bytes(body)
            return Generated(output, {"endpoint": f"{base}/audio/speech"})
        if capability == "image":
            size = self.config.get("image_size", f"{request['width']}x{request['height']}")
            payload = {"model": self.config["model_id"], "prompt": request["prompt"], "n": 1,
                       "size": size, "response_format": "b64_json",
                       **({"seed": request["seed"]} if "seed" in request else {}), **extra}
            result = http_json("POST", f"{base}/images/generations", payload=payload,
                               headers=headers, timeout=timeout)
            try:
                data = base64.b64decode(result["data"][0]["b64_json"], validate=True)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise PluginError(f"{self.name}: image response lacks data[0].b64_json") from exc
            output = workdir / "image.png"
            output.write_bytes(data)
            return Generated(output, {"endpoint": f"{base}/images/generations", "size": size})
        raise PluginError(f"{self.name} cannot serve {capability!r}")
