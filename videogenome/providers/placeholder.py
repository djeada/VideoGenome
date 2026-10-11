"""Placeholder provider: deterministic stand-ins for animatics and previews.

Lets any template render end to end before models or footage exist, so
timing, layout and the mix can be reviewed. Outputs are labelled slates and
tones; they are never presented as speech, music or footage, and receipts
flag programmes that contain them.
"""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

from videogenome.plugins import CAPABILITIES, Generated, PluginError, Provider
from videogenome.providers.base import provider_schema

WORDS_PER_SECOND = 2.6
SLATE = "#2A2F3A"


def _silence(path: Path, seconds: float, rate: int = 48000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * max(1, round(seconds * rate)))


class PlaceholderProvider(Provider):
    summary = "Labelled slates and tones for animatics (never final media)"
    capabilities = frozenset({"*"})
    config_schema = provider_schema({"background": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}})

    def serves(self) -> frozenset[str]:
        declared = self.config.get("capabilities")
        return frozenset(declared) if declared else frozenset(CAPABILITIES)

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        media = request.get("media") or CAPABILITIES[capability]["media"][0]
        if media == "audio":
            # Placeholder audio is silence of the right length: timing stays reviewable,
            # and nothing fake (tones, beeps, drones) can leak into a mix or a master.
            output = workdir / "placeholder.wav"
            if capability in ("speech", "voice_conversion"):
                words = len(request.get("text", "placeholder speech").split())
                seconds = min(request.get("max_seconds", math.inf), 0.4 + words / WORDS_PER_SECOND)
            else:
                seconds = request.get("duration_seconds", 4.0)
            _silence(output, seconds)
            return Generated(output, {"placeholder": True, "seconds": round(seconds, 3), "silent": True})

        width, height = request.get("width", 1280), request.get("height", 720)
        label = f"PLACEHOLDER {capability.upper()}"
        caption = (request.get("prompt") or request.get("text") or request.get("style") or "")[:240]
        (workdir / "label.txt").write_text(label, encoding="utf-8")
        (workdir / "caption.txt").write_text(caption or " ", encoding="utf-8")
        background = self.config.get("background", SLATE)
        size = max(18, height // 22)
        draw = (f"drawtext=textfile=label.txt:expansion=none:font=Sans:fontsize={size * 2}:"
                f"fontcolor=white@0.85:x=(w-text_w)/2:y=h*0.38,"
                f"drawtext=textfile=caption.txt:expansion=none:font=Sans:fontsize={size}:"
                f"fontcolor=white@0.7:x=(w-text_w)/2:y=h*0.55")
        if media == "image":
            output = workdir / "placeholder.png"
            graph = f"color=c=0x{background[1:]}:s={width}x{height}:d=1,{draw}"
            command = ["-f", "lavfi", "-i", graph, "-frames:v", "1", str(output)]
        else:
            fps = request.get("fps", 24)
            seconds = request.get("duration_seconds", 3.0)
            output = workdir / "placeholder.mp4"
            # A sweeping bar shows motion and timing without pretending to be footage.
            graph = (f"color=c=0x{background[1:]}:s={width}x{height}:r={fps}:d={seconds:.6f}[bg];"
                     f"color=c=white@0.35:s={max(4, width // 80)}x{height}:r={fps}:d={seconds:.6f}[bar];"
                     f"[bg][bar]overlay=x='(w-overlay_w)*t/{seconds:.6f}':y=0,{draw},format=yuv420p")
            command = ["-f", "lavfi", "-i", graph, "-frames:v", str(round(seconds * fps)),
                       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(output)]
        completed = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *command],
                                   capture_output=True, text=True, cwd=workdir, check=False)
        if completed.returncode or not output.is_file():
            raise PluginError(f"placeholder {media} failed: {completed.stderr[-400:]}")
        return Generated(output, {"placeholder": True})
