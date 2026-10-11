"""Generic CLI adapter: wrap any local tool that writes a media file.

Examples: Piper, espeak-ng, Kokoro/Qwen scripts, stable-diffusion.cpp,
Type-Simulator reels, ``blender -b --python turntable.py``. The command is
an argv list from the operator's profile and is never run through a shell.
Free text (script, prompt, direction) reaches the tool via stdin,
``{text_file}``-style files, or as an option value; never as a bare
positional argument.
"""
from __future__ import annotations

import sys
from pathlib import Path

from videogenome.plugins import Generated, PluginError, Provider
from videogenome.providers.base import (
    EXTENSION_SCHEMA, check_argv_free_text, drop_missing, fill, output_extension, provider_schema,
    run_process, write_text_files,
)


class CommandProvider(Provider):
    summary = "Run a local CLI tool (argv list, no shell) that writes {output}"
    capabilities = frozenset({"*"})
    config_schema = provider_schema({
        "argv": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "stdin": {"type": "string"},
        "extension": EXTENSION_SCHEMA,
        "env": {"type": "object", "additionalProperties": {"type": "string"}},
        "cwd": {"type": "string"},
        "defaults": {"type": "object", "additionalProperties": {"type": ["string", "number", "integer"]}},
    }, required=["argv", "extension", "capabilities"])

    def __init__(self, name: str, config: dict, **kwargs) -> None:
        super().__init__(name, config, **kwargs)
        check_argv_free_text(config["argv"], f"command provider {name!r}")
        if "{" in config["argv"][0] and config["argv"][0] != "{python}":
            raise PluginError(f"command provider {name!r}: the executable must be fixed")

    def check(self) -> list[tuple[str, str]]:
        import shutil
        executable = self.config["argv"][0]
        if executable == "{python}" or shutil.which(executable) or Path(executable).is_file():
            return [("OK", f"{executable} found")]
        return [("FAIL", f"{executable} not found on PATH")]

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        output = workdir / f"output{output_extension(self.config, request)}"
        values = {
            **self.config.get("defaults", {}), **request,
            **write_text_files(request, workdir),
            "output": str(output), "workdir": str(workdir),
            "profile_dir": str(self.base_dir), "capability": capability, "python": sys.executable,
        }
        argv = drop_missing(fill(self.config["argv"], values))
        stdin = fill(self.config["stdin"], values) if "stdin" in self.config else None
        cwd = Path(fill(self.config["cwd"], values)) if "cwd" in self.config else workdir
        env = {key: str(fill(value, values)) for key, value in self.config.get("env", {}).items()}
        completed = run_process(argv, stdin=stdin, cwd=cwd, env=env,
                                timeout=self.config.get("timeout_seconds", 1800),
                                label=f"command provider {self.name!r}")
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError(f"command provider {self.name!r} did not write {output.name}: "
                              f"{completed.stderr[-600:]}")
        return Generated(output, {"executable": self.config["argv"][0]})
