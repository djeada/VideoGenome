"""Procedural provider: render catalog recipes (Python, browser JS/WebGL) on demand.

Serves the ``procedural`` capability (request names a recipe, preset and params)
and, when the profile configures defaults, ordinary capabilities such as
``music`` or ``video``. A request's ``style`` role then selects a preset.
Output is MIT (or the recipe's declared licence), deterministic and free of
third-party material.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from videogenome.plugins import Generated, PluginError, Provider
from videogenome.procedural import catalog
from videogenome.providers.base import provider_schema, run_process
from videogenome.resources import PACKAGE

EXTENSIONS = {"video": ".mp4", "image": ".png", "audio": ".wav"}
DEFAULT_SPEC = {"type": "object", "additionalProperties": False, "required": ["recipe"],
                "properties": {"recipe": {"type": "string"}, "preset": {"type": "string"},
                               "params": {"type": "object"}}}


class ProceduralProvider(Provider):
    summary = "Render procedural recipes (Python/numpy, JS/WebGL in headless Chromium)"
    reports_rights = True
    capabilities = frozenset({"procedural", "music", "sound", "video", "image"})
    config_schema = provider_schema({
        "runtimes": {"type": "object", "additionalProperties": False,
                     "properties": {"python": {"type": "string"}, "browser": {"type": "string"}}},
        "recipe_dirs": {"type": "array", "items": {"type": "string"}},
        "defaults": {"type": "object", "additionalProperties": DEFAULT_SPEC},
    })

    def serves(self) -> frozenset[str]:
        return frozenset({"procedural", *self.config.get("defaults", {})})

    def _dirs(self) -> list[Path]:
        return [Path(d) if Path(d).is_absolute() else self.base_dir / d
                for d in self.config.get("recipe_dirs", [])]

    def check(self) -> list[tuple[str, str]]:
        rows = []
        try:
            recipes = catalog.discover(self._dirs())
            rows.append(("OK", f"{len(recipes)} recipes"))
        except Exception as exc:  # noqa: BLE001
            return [("FAIL", str(exc))]
        runtimes = {r.data["runtime"] for r in recipes.values()}
        python = self._interpreter("python")
        probes = {"python": "import numpy, scipy", "browser": "import playwright"}
        for runtime in sorted(runtimes):
            try:
                run_process([self._interpreter(runtime), "-c", probes[runtime]], stdin=None,
                            cwd=self.base_dir, env=self._env(), timeout=60, label=runtime)
                rows.append(("OK", f"{runtime} runtime ready ({python})"))
            except PluginError as exc:
                rows.append(("WARN", f"{runtime} recipes unavailable: {exc}"))
        return rows

    def _interpreter(self, runtime: str) -> str:
        value = self.config.get("runtimes", {}).get(runtime, "{python}")
        return sys.executable if value == "{python}" else value

    @staticmethod
    def _env() -> dict[str, str]:
        # Recipes import videogenome.procedural.kit even from another interpreter.
        existing = os.environ.get("PYTHONPATH")
        root = str(PACKAGE.parent)
        return {"PYTHONPATH": root + (os.pathsep + existing if existing else "")}

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        if capability == "procedural":
            recipe_id, preset, params = request.get("recipe"), request.get("preset"), request.get("params", {})
        else:
            default = self.config.get("defaults", {}).get(capability)
            if default is None:
                raise PluginError(f"{self.name}: no default recipe configured for {capability!r}")
            recipe_id, preset, params = default["recipe"], default.get("preset"), default.get("params", {})
            style = request.get("style")
            if style:  # A style role may name a preset of the default recipe.
                preset = style
        if not recipe_id:
            raise PluginError("procedural request needs a recipe")
        recipe = catalog.get(recipe_id, self._dirs())
        if preset and preset not in recipe.data.get("presets", {}) and capability != "procedural":
            preset = default.get("preset")
        media = request.get("media") or recipe.data["media"][0]
        if media not in recipe.data["media"]:
            raise PluginError(f"recipe {recipe_id} cannot produce {media} (only {recipe.data['media']})")
        resolved = recipe.resolve(preset, params)
        spec = {"recipe": recipe_id, "params": resolved, "media": media,
                "width": request.get("width", 1280), "height": request.get("height", 720),
                "fps": request.get("fps", 24), "duration_seconds": request.get("duration_seconds", 4.0),
                "seed": request.get("seed", 0), "sample_rate": 48000}
        spec_path = workdir / "spec.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        output = workdir / f"procedural{EXTENSIONS[media]}"
        runtime = recipe.data["runtime"]
        if runtime == "python":
            argv = [self._interpreter("python"), str(recipe.entry), "--spec", str(spec_path), "--out", str(output)]
        else:
            argv = [self._interpreter("browser"), "-m", "videogenome.procedural.browser",
                    "--entry", str(recipe.entry), "--spec", str(spec_path), "--out", str(output)]
        run_process(argv, stdin=None, cwd=workdir, env=self._env(),
                    timeout=self.config.get("timeout_seconds", 3600), label=f"recipe {recipe_id}")
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError(f"recipe {recipe_id} produced no output")
        digest = recipe.sha256()
        licence = recipe.data["license"]
        return Generated(output, {
            "origin_type": "rendered",
            "rights": {"license": licence,
                       "evidence": f"Procedurally rendered by recipe {recipe_id} {recipe.data['version']} "
                                   f"({licence}, sha256 {digest[:16]}); no third-party material."},
            "recipe": {"id": recipe_id, "version": recipe.data["version"], "sha256": digest,
                       "preset": preset, "params": resolved, "runtime": runtime},
        })
