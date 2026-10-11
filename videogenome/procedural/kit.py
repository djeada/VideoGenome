"""Toolkit for Python recipes: spec I/O, writers, palettes, easing and noise.

A Python recipe is a script that calls :func:`run`:

    from videogenome.procedural import kit

    def render(spec: kit.Spec) -> None:
        with kit.VideoWriter(spec) as video:
            for frame in range(spec.frames):
                video.write(make_frame(spec, frame))

    if __name__ == "__main__":
        kit.run(render)

The runner calls ``python recipe.py --spec spec.json --out OUTPUT``. Everything
random must derive from ``spec.rng`` so a spec always renders identically.
Requires numpy (``pip install videogenome[procedural]``).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

SAMPLE_RATE = 48000


@dataclass
class Spec:
    recipe: str
    params: dict
    media: str
    width: int = 1280
    height: int = 720
    fps: int = 24
    duration_seconds: float = 4.0
    seed: int = 0
    sample_rate: int = SAMPLE_RATE
    output: Path = field(default_factory=lambda: Path("out"))

    @property
    def frames(self) -> int:
        return 1 if self.media == "image" else max(1, round(self.duration_seconds * self.fps))

    @property
    def samples(self) -> int:
        return max(1, round(self.duration_seconds * self.sample_rate))

    @property
    def rng(self) -> np.random.Generator:
        return np.random.default_rng(self.seed)

    @property
    def aspect(self) -> float:
        return self.width / self.height


def run(render: Callable[[Spec], None]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.spec.read_text(encoding="utf-8"))
    known = {k: data[k] for k in ("recipe", "params", "media", "width", "height", "fps",
                                  "duration_seconds", "seed", "sample_rate") if k in data}
    spec = Spec(**known, output=args.out)
    render(spec)
    if not spec.output.is_file() or spec.output.stat().st_size == 0:
        sys.exit(f"recipe {spec.recipe} wrote no output")


# --------------------------------------------------------------------------
# Writers


class VideoWriter:
    """Pipe float [0,1] or uint8 RGB frames (H x W x 3) into an H.264 file or PNG."""

    def __init__(self, spec: Spec, *, crf: int = 14) -> None:
        self.spec = spec
        self.count = 0
        if spec.media == "image":
            command = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{spec.width}x{spec.height}",
                       "-i", "-", "-frames:v", "1", str(spec.output)]
        else:
            command = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{spec.width}x{spec.height}",
                       "-r", str(spec.fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                       "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                       str(spec.output)]
        self.process = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *command],
                                        stdin=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        if frame.dtype != np.uint8:
            frame = to_uint8(frame)
        if frame.shape != (self.spec.height, self.spec.width, 3):
            raise ValueError(f"frame shape {frame.shape} != {(self.spec.height, self.spec.width, 3)}")
        assert self.process.stdin is not None
        self.process.stdin.write(np.ascontiguousarray(frame).tobytes())
        self.count += 1

    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(self, *exc) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        if self.process.wait() != 0:
            raise RuntimeError("ffmpeg failed to encode recipe frames")


def to_uint8(frame: np.ndarray, *, dither: bool = True, rng: np.random.Generator | None = None) -> np.ndarray:
    """Quantise with triangular dither so smooth gradients do not band."""
    data = np.clip(frame, 0.0, 1.0) * 255.0
    if dither:
        rng = rng or np.random.default_rng(0)
        data = data + (rng.random(data.shape[:2] + (1,), dtype=np.float32)
                       - rng.random(data.shape[:2] + (1,), dtype=np.float32))
    return np.clip(np.round(data), 0, 255).astype(np.uint8)


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write float audio (n,) or (n, 2) in [-1, 1] as 24-bit stereo PCM."""
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    audio = np.clip(np.nan_to_num(audio), -1.0, 1.0)
    ints = np.round(audio * (2 ** 23 - 1)).astype("<i4")
    packed = np.ascontiguousarray(ints).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(3)
        handle.setframerate(sample_rate)
        handle.writeframes(packed)


# --------------------------------------------------------------------------
# Colour: palettes are mixed in OKLab so gradients stay vivid and even.


def hex_to_rgb(color: str) -> np.ndarray:
    color = color.lstrip("#")
    return np.array([int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]], dtype=np.float32)
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]], dtype=np.float32)


def srgb_to_oklab(c: np.ndarray) -> np.ndarray:
    lms = srgb_to_linear(c) @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    lms = lab @ np.linalg.inv(_M2).T
    return linear_to_srgb((lms ** 3) @ np.linalg.inv(_M1).T)


def palette_lut(colors: list[str], size: int = 1024, *, loop: bool = False) -> np.ndarray:
    """A (size, 3) sRGB lookup table interpolated in OKLab between the colours."""
    stops = srgb_to_oklab(np.stack([hex_to_rgb(c) for c in colors]))
    if loop:
        stops = np.concatenate([stops, stops[:1]])
    positions = np.linspace(0, 1, len(stops))
    x = np.linspace(0, 1, size)
    lab = np.stack([np.interp(x, positions, stops[:, i]) for i in range(3)], axis=1)
    return np.clip(oklab_to_srgb(lab), 0, 1).astype(np.float32)


def sample_lut(lut: np.ndarray, values: np.ndarray) -> np.ndarray:
    index = np.clip(values, 0, 1) * (len(lut) - 1)
    low = np.floor(index).astype(np.int32)
    high = np.minimum(low + 1, len(lut) - 1)
    t = (index - low)[..., None]
    return lut[low] * (1 - t) + lut[high] * t


# --------------------------------------------------------------------------
# Motion and noise


def smoothstep(x: np.ndarray | float) -> np.ndarray | float:
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def ease_in_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


class ValueNoise3:
    """Seeded, tileable-in-time 3D value noise with smooth interpolation."""

    def __init__(self, seed: int, size: int = 256) -> None:
        rng = np.random.default_rng(seed)
        self.size = size
        self.table = rng.random(size, dtype=np.float32)
        self.perm = np.concatenate([rng.permutation(size)] * 2).astype(np.int32)

    def _hash(self, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
        p, s = self.perm, self.size
        return self.table[p[p[p[x % s] + y % s] + z % s]]

    def __call__(self, x: np.ndarray, y: np.ndarray, z: float | np.ndarray) -> np.ndarray:
        z = np.broadcast_to(np.asarray(z, dtype=np.float32), x.shape)
        xi, yi, zi = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32), np.floor(z).astype(np.int32)
        xf, yf, zf = smoothstep(x - xi), smoothstep(y - yi), smoothstep(z - zi)
        result = 0.0
        for dx in (0, 1):
            wx = xf if dx else 1 - xf
            for dy in (0, 1):
                wy = yf if dy else 1 - yf
                for dz in (0, 1):
                    wz = zf if dz else 1 - zf
                    result = result + wx * wy * wz * self._hash(xi + dx, yi + dy, zi + dz)
        return result

    def fbm(self, x: np.ndarray, y: np.ndarray, z: float, octaves: int = 4,
            lacunarity: float = 2.0, gain: float = 0.5) -> np.ndarray:
        total, amplitude, norm = 0.0, 1.0, 0.0
        for octave in range(octaves):
            total = total + amplitude * self(x, y, z + octave * 17.31)
            norm += amplitude
            x, y = x * lacunarity + 3.7, y * lacunarity - 1.9
            amplitude *= gain
        return total / norm


def grid(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Normalised coordinates: y in [0, 1], x scaled by the aspect ratio."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    return xs / height, ys / height


def vignette(width: int, height: int, strength: float) -> np.ndarray:
    xs, ys = np.meshgrid(np.linspace(-1, 1, width, dtype=np.float32),
                         np.linspace(-1, 1, height, dtype=np.float32))
    radius = np.sqrt((xs * width / height) ** 2 + ys ** 2) / np.sqrt((width / height) ** 2 + 1)
    return (1 - strength * smoothstep((radius - 0.35) / 0.75))[..., None]


def film_grain(rng: np.random.Generator, height: int, width: int, amount: float) -> np.ndarray:
    return (rng.standard_normal((height, width, 1), dtype=np.float32) * amount)


# --------------------------------------------------------------------------
# Parallel frame rendering


def frames_in_parallel(make_frame: Callable[[Spec, int], np.ndarray], spec: Spec,
                       workers: int | None = None, chunk: int = 4):
    """Yield ``make_frame(spec, i)`` for every frame, in order, using worker processes.

    ``make_frame`` must be a module-level function and derive all randomness from
    ``spec.seed`` and the frame index, so parallel output equals serial output.
    """
    import multiprocessing
    import os
    from concurrent.futures import ProcessPoolExecutor
    from functools import partial

    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 1))
    if workers == 1 or spec.frames < 8:
        for index in range(spec.frames):
            yield make_frame(spec, index)
        return
    context = multiprocessing.get_context("fork") if hasattr(os, "fork") else None
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        yield from pool.map(partial(make_frame, spec), range(spec.frames), chunksize=chunk)
