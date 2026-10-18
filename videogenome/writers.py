"""Writer adapters: language models that propose copy for ``videogenome fill``.

``openai-chat`` speaks ``POST {base_url}/chat/completions``, which Ollama,
llama.cpp's server, vLLM, LocalAI, LM Studio and hosted APIs all accept.
``command`` pipes the conversation to any CLI on stdin (``llm``, ``claude -p``,
a llama.cpp binary, a script) and reads the reply from stdout.

Briefs and replies are untrusted text. They travel only in request bodies or
on stdin, never in URLs, argv or shell strings.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from videogenome.plugins import PluginError, Writer, Written
from videogenome.providers.base import api_headers, http_json, run_process

MODEL_PROPERTY = {
    "type": "object", "additionalProperties": False,
    "properties": {"name": {"type": "string"}, "version": {"type": "string"},
                   "source": {"type": "string"}, "license": {"type": "string"}},
}
COMMON = {
    "model": MODEL_PROPERTY,
    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600},
    "notes": {"type": "string"},
}
THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)


def transcript(system: str, messages: list[dict], schema: dict) -> str:
    """Flatten a conversation for tools that take one prompt on stdin."""
    parts = [system.strip(), "",
             "Reply with one JSON object only (no prose, no code fences) matching this JSON Schema:",
             json.dumps(schema, separators=(",", ":")), ""]
    for message in messages:
        label = "ASSISTANT" if message["role"] == "assistant" else "USER"
        parts += [f"### {label}", message["content"].strip(), ""]
    parts.append("### ASSISTANT")
    return "\n".join(parts)


class OpenAIChatWriter(Writer):
    summary = "POST to an OpenAI-compatible /chat/completions server (Ollama, llama.cpp, vLLM, hosted APIs)"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["base_url", "model_id"],
        "properties": {
            **COMMON,
            "base_url": {"type": "string", "pattern": "^https?://"},
            "model_id": {"type": "string", "minLength": 1},
            "api_key_env": {"type": "string", "pattern": "^[A-Z_][A-Z0-9_]*$"},
            "temperature": {"type": "number", "minimum": 0, "maximum": 2},
            "max_tokens": {"type": "integer", "minimum": 64, "maximum": 32768},
            # json_schema: constrained decoding where the server supports it;
            # json_object: valid JSON only; none: rely on the prompt.
            "structured_output": {"enum": ["json_schema", "json_object", "none"]},
            "extra": {"type": "object"},
        },
    }

    def check(self) -> list[tuple[str, str]]:
        base = self.config["base_url"].rstrip("/")
        try:
            listing = http_json("GET", f"{base}/models", headers=api_headers(self.config), timeout=5)
        except PluginError as exc:
            return [("WARN", f"server not reachable now: {exc}")]
        ids = {item.get("id") for item in listing.get("data", []) if isinstance(item, dict)}
        if ids and self.config["model_id"] not in ids:
            return [("WARN", f"{base} reachable but does not list model {self.config['model_id']!r}")]
        return [("OK", f"{base} serves {self.config['model_id']}")]

    def write(self, system: str, messages: list[dict], schema: dict) -> Written:
        base = self.config["base_url"].rstrip("/")
        mode = self.config.get("structured_output", "json_schema")
        payload = {
            "model": self.config["model_id"],
            "messages": [{"role": "system", "content": system},
                         *({"role": m["role"], "content": m["content"]} for m in messages)],
            "temperature": self.config.get("temperature", 0.4),
            "stream": False,
            **({"max_tokens": self.config["max_tokens"]} if "max_tokens" in self.config else {}),
        }
        if mode == "json_schema":
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "slots", "schema": schema, "strict": False}}
        elif mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        payload.update(self.config.get("extra", {}))
        reply = http_json("POST", f"{base}/chat/completions", payload=payload,
                          headers=api_headers(self.config),
                          timeout=self.config.get("timeout_seconds", 300))
        try:
            choice = reply["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PluginError(f"{self.name}: reply lacks choices[0].message.content") from exc
        if not isinstance(text, str) or not text.strip():
            raise PluginError(f"{self.name}: empty reply (finish_reason={choice.get('finish_reason')!r})")
        usage = reply.get("usage", {}) if isinstance(reply.get("usage"), dict) else {}
        return Written(THINKING.sub("", text).strip(), {
            "endpoint": f"{base}/chat/completions", "model_id": self.config["model_id"],
            "served_model": reply.get("model"), "finish_reason": choice.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        })


class CommandWriter(Writer):
    summary = "Pipe the conversation to a CLI on stdin and read JSON from stdout"
    config_schema = {
        "type": "object", "additionalProperties": False, "required": ["argv"],
        "properties": {
            **COMMON,
            "argv": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
            "cwd": {"type": "string"},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            # transcript: one flattened prompt; messages: {"system", "messages", "schema"} as JSON.
            "stdin": {"enum": ["transcript", "messages"]},
        },
    }

    def check(self) -> list[tuple[str, str]]:
        import shutil
        executable = self.config["argv"][0]
        if executable == "{python}" or shutil.which(executable):
            return [("OK", f"{executable} available")]
        return [("WARN", f"executable not found: {executable}")]

    def write(self, system: str, messages: list[dict], schema: dict) -> Written:
        argv = list(self.config["argv"])
        if any("{" in item and item != "{python}" for item in argv):
            raise PluginError(f"{self.name}: argv takes no placeholders; the prompt is sent on stdin")
        if self.config.get("stdin", "transcript") == "messages":
            stdin = json.dumps({"system": system, "messages": messages, "schema": schema})
        else:
            stdin = transcript(system, messages, schema)
        cwd = Path(self.config.get("cwd") or self.base_dir)
        completed = run_process(argv, stdin=stdin, cwd=cwd, env=self.config.get("env", {}),
                                timeout=self.config.get("timeout_seconds", 600), label=self.name)
        text = THINKING.sub("", completed.stdout).strip()
        if not text:
            raise PluginError(f"{self.name}: wrote nothing to stdout")
        return Written(text, {"argv0": argv[0]})
