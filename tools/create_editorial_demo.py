"""Create reproducible, original test media for the audio/caption example.

The tones stand in for music and narration; they are not generated speech.
No downloads, API keys, people, recordings or third-party media are involved.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path

from videogenome.compiler import ROOT


def write_tone(path: Path, frequency: float, seconds: float, *, sample_rate: int = 48000,
               silence_seconds: float = 0) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        # Moderate amplitude leaves room for overlapping test sources.
        handle.writeframes(b"".join(
            struct.pack("<h", 0 if sample < silence_seconds * sample_rate else
                        round(8000 * math.sin(2 * math.pi * frequency * sample / sample_rate)))
            for sample in range(round(seconds * sample_rate))
        ))


def create_demo(directory: Path, *, brief: str = "editing") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    write_tone(directory / "music.wav", 220, 9, silence_seconds=1)
    write_tone(directory / "narration.wav", 660, 4, sample_rate=44100)
    width, height = 640, 360
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            color = (20, 32, 46)
            for top, left, right, fill in (
                (60, 60, 580, (61, 190, 168)),
                (116, 60, 580, (63, 104, 166)),
                (172, 190, 450, (228, 163, 77)),
            ):
                if left <= x < right and top <= y < top + 32:
                    color = fill
            if 318 <= x < 322 and 44 <= y < 220:
                color = (240, 244, 250)
            pixels.extend(color)
    (directory / "timeline.ppm").write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)
    job = json.loads((ROOT / "examples/captioned-explainer/job.json").read_text(encoding="utf-8"))
    if brief == "learning":
        job["id"] = "sample.captioned-learning"
        job["inputs"].update({
            "title": "Learn one step at a time",
            "caption_intro": "Start with one clear idea.",
            "caption_detail": "Connect it to what you know.",
            "caption_close": "Try it. Reflect. Repeat.",
        })
    manifest = directory / "job.json"
    manifest.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--brief", choices=["editing", "learning"], default="editing")
    args = parser.parse_args()
    print(create_demo(args.output.resolve(), brief=args.brief))


if __name__ == "__main__":
    main()
