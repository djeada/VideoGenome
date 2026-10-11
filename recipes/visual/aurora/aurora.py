"""Aurora: a slowly flowing, domain-warped gradient in a locked palette.

The field is three nested fBm lookups (domain warping) evaluated at reduced
resolution, upscaled smoothly, mapped through an OKLab palette, then finished
at full resolution with vignette, film grain and dithering so it never bands.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from videogenome.procedural import kit


def make_frame(spec: kit.Spec, index: int) -> np.ndarray:
    p = spec.params
    scale = p["detail_scale"]
    low_w = max(16, round(spec.width * scale))
    low_h = max(9, round(spec.height * scale))
    noise = kit.ValueNoise3(spec.seed)
    xs, ys = kit.grid(low_w, low_h)
    angle = math.radians(p["flow_angle"])
    t = index / spec.fps * p["speed"]
    drift_x, drift_y = math.cos(angle) * t * 0.6, math.sin(angle) * t * 0.6
    x = xs * p["frequency"] + drift_x
    y = ys * p["frequency"] + drift_y
    q1 = noise.fbm(x, y, t, octaves=3)
    q2 = noise.fbm(x + 5.2, y + 1.3, t + 3.1, octaves=3)
    r1 = noise.fbm(x + p["warp"] * 3 * q1 + 1.7, y + p["warp"] * 3 * q2 + 9.2, t * 0.8, octaves=3)
    r2 = noise.fbm(x + p["warp"] * 3 * q1 + 8.3, y + p["warp"] * 3 * q2 + 2.8, t * 0.8 + 7.0, octaves=3)
    field = noise.fbm(x + p["warp"] * 3 * r1, y + p["warp"] * 3 * r2, t * 0.5 + 11.0, octaves=3, gain=0.45)
    # Stretch contrast around the middle so every palette stop appears.
    field = kit.smoothstep((field - 0.5) * p["contrast"] * 2.2 + 0.5)
    glow = kit.smoothstep(r1 * 1.4 - 0.3)
    field = ndimage.zoom(field, (spec.height / low_h, spec.width / low_w), order=3, mode="nearest")
    glow = ndimage.zoom(glow, (spec.height / low_h, spec.width / low_w), order=1, mode="nearest")
    lut = kit.palette_lut(p["palette"])
    rgb = kit.sample_lut(lut, field[: spec.height, : spec.width])
    rgb = rgb * (p["brightness"] + p["glow"] * glow[: spec.height, : spec.width, None])
    rgb = rgb * kit.vignette(spec.width, spec.height, p["vignette"])
    rng = np.random.default_rng((spec.seed, index))
    rgb = rgb + kit.film_grain(rng, spec.height, spec.width, p["grain"])
    return kit.to_uint8(rgb, rng=rng)


def render(spec: kit.Spec) -> None:
    with kit.VideoWriter(spec) as video:
        for frame in kit.frames_in_parallel(make_frame, spec):
            video.write(frame)


if __name__ == "__main__":
    kit.run(render)
