"""Anti-aliased drawing helpers for Python visual recipes (numpy only).

All drawing happens in *linear light* float32 canvases (H x W x 3) so additive
light (bokeh, glows, dots) blends physically; convert with
:func:`linear_to_display` at the end. Edges are analytic coverage (sub-pixel
accurate), so no supersampling is needed to avoid jaggies.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from videogenome.procedural import kit


def splat_discs(canvas: np.ndarray, xs: np.ndarray, ys: np.ndarray, radii: np.ndarray,
                colors: np.ndarray, intensity: np.ndarray | float = 1.0,
                softness: np.ndarray | float = 1.0, ring: np.ndarray | float = 0.0,
                ring_width: float = 0.12) -> None:
    """Additively draw anti-aliased discs into ``canvas`` (linear RGB).

    ``softness`` is the edge falloff width in pixels (>= ~0.8 for crisp but
    alias-free edges; large values give out-of-focus discs). ``ring`` adds a
    brighter rim (bokeh "onion ring" look) as a fraction of the fill.
    """
    height, width, _ = canvas.shape
    count = len(xs)
    if count == 0:
        return
    xs, ys = np.asarray(xs, np.float32), np.asarray(ys, np.float32)
    radii = np.maximum(np.asarray(radii, np.float32), 0.3)
    colors = np.asarray(colors, np.float32).reshape(count, 3)
    intensity = np.broadcast_to(np.asarray(intensity, np.float32), (count,))
    softness = np.maximum(np.broadcast_to(np.asarray(softness, np.float32), (count,)), 0.6)
    ring = np.broadcast_to(np.asarray(ring, np.float32), (count,))
    halves = np.ceil(radii + softness).astype(np.int32) + 1
    # Skip discs entirely outside the canvas.
    visible = (xs + halves >= 0) & (xs - halves < width) & (ys + halves >= 0) & (ys - halves < height)
    flat_canvas = canvas.reshape(-1, 3)
    for half in np.unique(halves[visible]):
        index = np.nonzero(visible & (halves == half))[0]
        offsets = np.arange(-half, half + 1, dtype=np.int32)
        cx = np.floor(xs[index]).astype(np.int32)
        cy = np.floor(ys[index]).astype(np.int32)
        px = cx[:, None, None] + offsets[None, None, :]
        py = cy[:, None, None] + offsets[None, :, None]
        dx = px + 0.5 - xs[index, None, None]
        dy = py + 0.5 - ys[index, None, None]
        distance = np.sqrt(dx * dx + dy * dy)
        r = radii[index, None, None]
        soft = softness[index, None, None]
        coverage = kit.smoothstep((r - distance) / soft + 0.5)
        if np.any(ring[index] > 0):
            band = np.maximum(r * ring_width, 0.6)
            rim = np.exp(-((distance - (r - band)) / band) ** 2)
            coverage = coverage * (1 + ring[index, None, None] * rim)
        weights = coverage * intensity[index, None, None]
        inside = (px >= 0) & (px < width) & (py >= 0) & (py < height) & (weights > 1e-5)
        flat = (py * width + px)[inside]
        w = weights[inside]
        owner = np.broadcast_to(np.arange(len(index))[:, None, None], inside.shape)[inside]
        for channel in range(3):
            flat_canvas[:, channel] += np.bincount(flat, weights=w * colors[index][owner, channel],
                                                   minlength=height * width)


def linear_gradient(width: int, height: int, colors: list[str], angle_degrees: float = 90.0) -> np.ndarray:
    """sRGB float gradient across the frame (OKLab-interpolated), angle 90 = top to bottom."""
    lut = kit.palette_lut(colors)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    angle = np.radians(angle_degrees)
    direction = np.array([np.cos(angle), np.sin(angle)], np.float32)
    projection = ((xs - width / 2) * direction[0] + (ys - height / 2) * direction[1])
    span = abs(width / 2 * direction[0]) + abs(height / 2 * direction[1])
    return kit.sample_lut(lut, projection / (2 * span) + 0.5)


def radial_glow(width: int, height: int, cx: float, cy: float, radius: float) -> np.ndarray:
    """Soft (H x W x 1) radial falloff, 1 at the centre."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / max(radius, 1e-3)
    return np.exp(-d * d)[..., None]


def blur(image: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return image
    return ndimage.gaussian_filter(image, sigma=(sigma, sigma, 0), mode="nearest")


def upscale(image: np.ndarray, height: int, width: int, order: int = 1) -> np.ndarray:
    """Smoothly resize an (h x w x c) float image to exactly (height x width)."""
    h, w = image.shape[:2]
    if (h, w) == (height, width):
        return image
    zoomed = ndimage.zoom(image, (height / h, width / w, 1), order=order, mode="nearest")
    return zoomed[:height, :width]


def tonemap(linear: np.ndarray, exposure: float = 1.0, knee: float = 0.6) -> np.ndarray:
    """Identity below ``knee``; above it highlights roll off smoothly towards 1 instead of clipping."""
    x = np.maximum(linear * exposure, 0)
    over = np.maximum(x - knee, 0)
    return np.where(x < knee, x, knee + (1 - knee) * (1 - np.exp(-over / (1 - knee))))


def linear_to_display(linear: np.ndarray, exposure: float = 1.0) -> np.ndarray:
    return kit.linear_to_srgb(tonemap(linear, exposure))
