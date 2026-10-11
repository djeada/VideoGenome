"""Bokeh: out-of-focus lights drifting slowly through several depths of field.

Discs are drawn additively in linear light at reduced resolution (bokeh is
soft by nature), with depth controlling size, defocus, brightness and parallax
speed. Near discs get a faint bright rim, like real lens bokeh. A deep
gradient, a slow coloured haze, a highlight roll-off, vignette, grain and
dithering finish the frame. Every disc's position is a pure function of the
frame index, so frames render independently and in parallel.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from videogenome.procedural import kit, shapes


def _discs(spec: kit.Spec, width: int, height: int) -> dict[str, np.ndarray]:
    p = spec.params
    rng = np.random.default_rng((spec.seed, 7919))
    count = p["count"]
    layers = p["layers"]
    layer = rng.integers(0, layers, count)
    depth = (layer + rng.random(count) * 0.8) / max(layers - 0.2, 1)  # 0 far .. 1 near
    size = p["size_min"] + (p["size_max"] - p["size_min"]) * (0.35 + 0.65 * rng.random(count)) * depth ** 1.8
    unit = min(width, height)  # Sizes follow the short side so 9:16 matches 16:9.
    radius = np.maximum(size * unit, 1.0)
    margin = float(radius.max() * (1.6 + p["softness"])) + 4
    palette = np.stack([kit.srgb_to_linear(kit.hex_to_rgb(c)) for c in p["palette"]])
    colors = palette[rng.integers(0, len(palette), count)]
    # Mix of a few soft clusters and a uniform scatter: organic, not polka-dot.
    clusters = max(1, round(1 + 3 * p["clustering"]))
    centres = rng.uniform([0, 0], [width, height], (clusters, 2))
    which = rng.integers(0, clusters, count)
    clustered = rng.random(count) < p["clustering"]
    spread = np.array([width, height]) * (0.28 - 0.12 * p["clustering"])
    x = np.where(clustered, centres[which, 0] + rng.normal(0, 1, count) * spread[0],
                 rng.uniform(-margin, width + margin, count))
    y = np.where(clustered, centres[which, 1] + rng.normal(0, 1, count) * spread[1],
                 rng.uniform(-margin, height + margin, count))
    return {
        "x": x, "y": y,
        "radius": radius, "depth": depth, "colors": colors, "margin": np.float32(margin),
        "base": 0.45 + 0.55 * rng.random(count),
        "twinkle_rate": rng.uniform(0.05, 0.22, count), "twinkle_phase": rng.uniform(0, 2 * math.pi, count),
        "wobble_rate": rng.uniform(0.03, 0.09, count), "wobble_phase": rng.uniform(0, 2 * math.pi, count),
    }


@lru_cache(maxsize=4)
def _static(width: int, height: int, background: tuple[str, ...], angle: float,
            vignette: float) -> tuple[np.ndarray, np.ndarray]:
    gradient = kit.srgb_to_linear(shapes.linear_gradient(width, height, list(background), angle))
    return gradient.astype(np.float32), kit.vignette(width, height, vignette)


def make_frame(spec: kit.Spec, index: int) -> np.ndarray:
    p = spec.params
    scale = p["detail_scale"]
    width, height = max(32, round(spec.width * scale)), max(32, round(spec.height * scale))
    d = _discs(spec, width, height)
    t = index / spec.fps
    angle = math.radians(p["drift_angle"])
    unit = min(width, height)
    speed = p["drift_speed"] * unit * (0.3 + 1.1 * d["depth"])  # parallax: near moves faster
    wobble = 0.01 * unit * np.sin(2 * math.pi * d["wobble_rate"] * t + d["wobble_phase"])
    margin = d["margin"]
    span_x, span_y = width + 2 * margin, height + 2 * margin
    xs = (d["x"] + math.cos(angle) * speed * t + wobble + margin) % span_x - margin
    ys = (d["y"] + math.sin(angle) * speed * t + wobble * 0.6 + margin) % span_y - margin

    twinkle = 1 + p["twinkle"] * 0.5 * np.sin(2 * math.pi * d["twinkle_rate"] * t + d["twinkle_phase"])
    near = d["depth"]
    # Defocus grows with nearness and the light spreads over a larger disc, so near
    # discs are big, soft and translucent while far ones are small, crisp points.
    softness = 0.7 + p["softness"] * d["radius"] * (0.15 + 0.85 * near)
    intensity = d["base"] * twinkle * (1.0 - 0.75 * near ** 0.8) * 0.75
    canvas = np.zeros((height, width, 3), np.float32)
    shapes.splat_discs(canvas, xs, ys, d["radius"], d["colors"], intensity=intensity,
                       softness=softness, ring=p["ring"] * (0.3 + 0.7 * near), ring_width=0.1)

    background, vignette = _static(width, height, tuple(p["background"]), p["background_angle"], p["vignette"])
    linear = background.copy()
    if p["haze"] > 0:
        haze_color = kit.srgb_to_linear(kit.hex_to_rgb(p["palette"][-1]))
        cx = width * (0.72 + 0.06 * math.sin(2 * math.pi * 0.02 * t))
        cy = height * (0.3 + 0.05 * math.cos(2 * math.pi * 0.017 * t))
        linear += p["haze"] * 0.05 * haze_color * shapes.radial_glow(width, height, cx, cy, max(width, height) * 0.6)
    light = canvas * p["brightness"]
    if p["bloom"] > 0:  # Wide soft glow around lights reads as luminous, not painted.
        light = light + p["bloom"] * shapes.blur(light, unit * 0.025)
    linear += light
    rgb = shapes.linear_to_display(linear) * vignette
    rgb = shapes.upscale(rgb, spec.height, spec.width, order=1)
    rng = np.random.default_rng((spec.seed, index))
    rgb = rgb + kit.film_grain(rng, spec.height, spec.width, p["grain"])
    return kit.to_uint8(rgb, rng=rng)


def render(spec: kit.Spec) -> None:
    with kit.VideoWriter(spec) as video:
        for frame in kit.frames_in_parallel(make_frame, spec):
            video.write(frame)


if __name__ == "__main__":
    kit.run(render)
