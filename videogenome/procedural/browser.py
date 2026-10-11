"""Browser runtime: render a JS/WebGL/Canvas recipe frame by frame in headless Chromium.

A browser recipe is an ``index.html`` that defines two globals:

    window.vgSetup = async (spec) => { ... }   // build scene; spec.params, spec.seed, sizes
    window.vgRender = (frame, t) => { ... }     // draw frame synchronously at time t (seconds)

The harness sets the viewport to the output size, blocks every non-file
request (recipes must be self-contained and offline), replaces Math.random
with a seeded generator, then screenshots each frame into FFmpeg. Frame
timing comes from the harness, never the wall clock, so output is exact.
Requires ``pip install playwright`` and a Chromium build (``playwright install
chromium-headless-shell``).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SEEDED_RANDOM = """
(() => {
  let a = (window.__vgSeed >>> 0) || 1;
  Math.random = () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
})();
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    frames = 1 if spec["media"] == "image" else max(1, round(spec["duration_seconds"] * fps))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("browser recipes need `pip install playwright` and `playwright install chromium-headless-shell`")

    if spec["media"] == "image":
        encode = ["-f", "image2pipe", "-c:v", "mjpeg", "-i", "-", "-frames:v", "1", str(args.out)]
    else:
        encode = ["-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(fps), "-i", "-",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p",
                  "-movflags", "+faststart", str(args.out)]
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file://")
                      else route.abort())
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.add_init_script(f"window.__vgSeed = {int(spec.get('seed', 0))};" + SEEDED_RANDOM)
        page.goto(args.entry.resolve().as_uri())
        page.evaluate("spec => window.vgSetup(spec)", spec)
        if errors:
            sys.exit(f"recipe setup failed: {errors[0]}")
        encoder = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *encode],
                                   stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        try:
            for frame in range(frames):
                page.evaluate("([f, t]) => window.vgRender(f, t)", [frame, frame / fps])
                # JPEG q100 capture is ~5x faster than PNG and visually lossless before H.264.
                encoder.stdin.write(page.screenshot(type="jpeg", quality=100,
                                                    clip={"x": 0, "y": 0, "width": width, "height": height}))
                if errors:
                    break
        finally:
            encoder.stdin.close()
            encoder.wait()
            browser.close()
    if errors:
        sys.exit(f"recipe raised in the browser: {errors[0]}")
    if encoder.returncode:
        sys.exit("ffmpeg failed to encode browser frames")


if __name__ == "__main__":
    main()
