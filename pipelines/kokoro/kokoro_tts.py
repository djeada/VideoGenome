"""Kokoro-82M narration for VideoGenome's command adapter (CPU is fine).

    python kokoro_tts.py --text-file script.txt --voice af_heart --out speech.wav [--speed 1.0]

The language comes from the voice prefix (a = American, b = British English,
e/f/h/i/j/p/z = other languages). Run with HF_HUB_OFFLINE=1 once weights are
cached. Requires: pip install kokoro soundfile (plus torch).

Install the environment at a SHORT path (e.g. ~/.cache/videogenome/kokoro):
libespeak-ng truncates data paths longer than ~160 characters and then fails
with "Error processing file '/home/runner/.../phontab'".
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

try:  # espeakng-loader wheels embed a stale build path; libespeak-ng honours this variable.
    import os

    import espeakng_loader
    os.environ.setdefault("ESPEAK_DATA_PATH", espeakng_loader.get_data_path())
except ImportError:
    pass

from kokoro import KPipeline  # noqa: E402 - after the espeak fix-up above


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    text = args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("empty text")
    pipeline = KPipeline(lang_code=args.voice[0], repo_id="hexgrad/Kokoro-82M")
    chunks = [np.asarray(audio, dtype=np.float32) for _, _, audio in
              pipeline(text, voice=args.voice, speed=args.speed) if audio is not None]
    if not chunks:
        raise SystemExit("Kokoro produced no audio")
    gap = np.zeros(int(0.12 * 24000), dtype=np.float32)
    audio = np.concatenate([part for chunk in chunks for part in (chunk, gap)][:-1])
    sf.write(str(args.out), audio, 24000, subtype="PCM_16")


if __name__ == "__main__":
    main()
