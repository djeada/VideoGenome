"""Dot wave: a perspective grid of dots rippling with interfering waves.

A plane of dots is tilted away from a pinhole camera; circular waves from a
few slowly wandering sources displace each dot along the plane normal and
modulate its size and brightness, like sound or data moving through a field.
Dots are analytic, anti-aliased discs in linear light with a soft glow and
depth fade; colour runs across the grid and optionally with wave height.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from videogenome.procedural import kit, shapes

DISTANCE = 2.4   # camera distance to the plane centre (plane units)
FOCAL = 1.1      # focal length in short-side lengths


@lru_cache(maxsize=4)
def _plane(spacing: float, tilt: float) -> tuple[np.ndarray, np.ndarray]:
    extent_u = 4.5 + 3.0 * tilt
    us = np.arange(-extent_u, extent_u + 1e-6, spacing, dtype=np.float32)
    vs = np.arange(-2.6, 1.6 + 4.0 * tilt + 1e-6, spacing, dtype=np.float32)
    grid_u, grid_v = np.meshgrid(us, vs)
    return grid_u.ravel(), grid_v.ravel()


@lru_cache(maxsize=4)
def _static(width: int, height: int, background: tuple[str, ...], vignette: float):
    gradient = kit.srgb_to_linear(shapes.linear_gradient(width, height, list(background), 90))
    return gradient.astype(np.float32), kit.vignette(width, height, vignette)


def make_frame(spec: kit.Spec, index: int) -> np.ndarray:
    p = spec.params
    width, height = spec.width, spec.height
    unit = min(width, height)
    t = index / spec.fps
    u, v = _plane(p["spacing"], p["tilt"])

    rng = np.random.default_rng((spec.seed, 104729))
    sources = p["sources"]
    origin = rng.uniform([-2.0, -1.0], [2.0, 2.5], (sources, 2)).astype(np.float32)
    orbit = rng.uniform(0.2, 0.6, sources)
    phase = rng.uniform(0, 2 * math.pi, sources)
    height_field = np.zeros_like(u)
    for k in range(sources):  # Sources wander slowly so the interference pattern evolves.
        sx = origin[k, 0] + orbit[k] * math.sin(0.05 * 2 * math.pi * t + phase[k])
        sy = origin[k, 1] + orbit[k] * math.cos(0.04 * 2 * math.pi * t + phase[k] * 1.3)
        distance = np.sqrt((u - sx) ** 2 + (v - sy) ** 2)
        height_field += np.sin(p["frequency"] * distance - 2 * math.pi * p["speed"] * t + phase[k]) / (1 + 0.25 * distance)
    wave = height_field / max(1.0, sources ** 0.5)          # roughly [-1, 1]
    displacement = p["amplitude"] * wave

    theta = math.radians(70 * p["tilt"])
    y_world = v * math.cos(theta) + displacement * math.sin(theta)
    z_world = v * math.sin(theta) - displacement * math.cos(theta) + DISTANCE
    visible = z_world > 0.35
    focal = FOCAL * unit
    sx = width / 2 + u * focal / np.maximum(z_world, 1e-3)
    sy = height / 2 + p["horizon"] * height - y_world * focal / np.maximum(z_world, 1e-3)
    lift = np.clip((wave + 1) / 2, 0, 1)                      # 0 trough .. 1 crest
    radius = p["dot_size"] * focal / np.maximum(z_world, 1e-3) * (1 - p["size_modulation"] * (1 - lift))
    on_screen = visible & (sx > -20) & (sx < width + 20) & (sy > -20) & (sy < height + 20) & (radius > 0.15)

    depth_fade = np.exp(-np.maximum(z_world - DISTANCE * 0.6, 0) * p["depth_fade"])
    level = (0.25 + 0.75 * lift ** 1.5) * depth_fade * p["brightness"]
    lut = kit.srgb_to_linear(kit.palette_lut(p["palette"]))
    across = np.clip(sx / width, 0, 1)                        # colour runs across the visible frame
    tone = np.clip((1 - p["color_by_height"]) * across + p["color_by_height"] * lift, 0, 1)
    colors = kit.sample_lut(lut, tone)

    canvas = np.zeros((height, width, 3), np.float32)
    # Sub-pixel dots fade by area instead of popping in and out.
    tiny = np.clip(radius / 0.8, 0, 1) ** 2
    shapes.splat_discs(canvas, sx[on_screen], sy[on_screen], np.maximum(radius[on_screen], 0.8),
                       colors[on_screen], intensity=(level * tiny)[on_screen], softness=0.9)
    if p["glow"] > 0:
        canvas = canvas + p["glow"] * shapes.blur(canvas, unit * 0.012)
    background, vignette = _static(width, height, tuple(p["background"]), p["vignette"])
    rgb = shapes.linear_to_display(background + canvas) * vignette
    noise = np.random.default_rng((spec.seed, index))
    rgb = rgb + kit.film_grain(noise, height, width, p["grain"])
    return kit.to_uint8(rgb, rng=noise)


def render(spec: kit.Spec) -> None:
    with kit.VideoWriter(spec) as video:
        for frame in kit.frames_in_parallel(make_frame, spec):
            video.write(frame)


if __name__ == "__main__":
    kit.run(render)
