"""Write an original, procedurally generated product model (.glb) for examples.

A smooth-shaded bottle-like lathe made from a fixed profile: no downloads,
scans or third-party assets. Pure Python, so it runs anywhere.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

# (radius, height) profile from the base to the cap.
PROFILE = [(0.0, 0.0), (0.42, 0.0), (0.46, 0.05), (0.46, 0.95), (0.40, 1.15),
           (0.18, 1.32), (0.17, 1.55), (0.20, 1.58), (0.20, 1.72), (0.0, 1.74)]
SEGMENTS = 48


def _lathe() -> tuple[list[float], list[float], list[int]]:
    positions, normals, indices = [], [], []
    for ring, (radius, height) in enumerate(PROFILE):
        before = PROFILE[max(ring - 1, 0)]
        after = PROFILE[min(ring + 1, len(PROFILE) - 1)]
        dr, dh = after[0] - before[0], after[1] - before[1]
        length = math.hypot(dr, dh) or 1.0
        nr, nh = dh / length, -dr / length
        for step in range(SEGMENTS + 1):
            angle = 2 * math.pi * step / SEGMENTS
            c, s = math.cos(angle), math.sin(angle)
            positions += [radius * c, height, radius * s]
            normals += [nr * c, nh, nr * s]
    width = SEGMENTS + 1
    for ring in range(len(PROFILE) - 1):
        for step in range(SEGMENTS):
            a, b = ring * width + step, ring * width + step + 1
            c, d = a + width, b + width
            indices += [a, c, b, b, c, d]
    return positions, normals, indices


def write_model(path: Path) -> Path:
    positions, normals, indices = _lathe()
    pos = struct.pack(f"<{len(positions)}f", *positions)
    nor = struct.pack(f"<{len(normals)}f", *normals)
    idx = struct.pack(f"<{len(indices)}H", *indices)
    idx += b"\0" * (-len(idx) % 4)
    binary = pos + nor + idx
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
    document = {
        "asset": {"version": "2.0", "generator": "VideoGenome tools/create_product_model.py"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "bottle"}],
        "materials": [{"name": "glass_amber", "pbrMetallicRoughness": {
            "baseColorFactor": [0.78, 0.42, 0.16, 1.0], "metallicFactor": 0.1, "roughnessFactor": 0.25}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos), "byteLength": len(nor), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos) + len(nor), "byteLength": len(indices) * 2, "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(xs), "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": len(xs), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": len(indices), "type": "SCALAR"}],
    }
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    body = (struct.pack("<II", len(text), 0x4E4F534A) + text +
            struct.pack("<II", len(binary), 0x004E4942) + binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, required=True)
    print(write_model(parser.parse_args().output))


if __name__ == "__main__":
    main()
