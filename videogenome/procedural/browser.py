"""Browser runtime: render HTML/JS/WebGL/Canvas/SVG frame by frame in headless Chromium.

Two kinds of page render frame-exactly:

* **Recipe contract.** The page defines ``window.vgSetup = async (spec) => {}``
  and ``window.vgRender = (frame, t) => {}``; the harness calls vgRender for
  every frame.
* **Ordinary animation code** (``mode: "clock"``). The page animates the way a
  person or model normally writes it: ``requestAnimationFrame`` loops,
  ``performance.now()``, ``Date``, timers, CSS animations and transitions,
  the Web Animations API, and libraries built on them (GSAP, Three.js clocks,
  anime.js). A virtual clock replaces all of them before any page script
  runs, and the harness advances it by exactly one frame between screenshots.
  The page reads its parameters from ``window.vgSpec``.

Either way the harness sets the viewport to the output size, blocks every
request outside the page's own directory (pages must be self-contained and
offline), seeds ``Math.random``, and pipes screenshots into FFmpeg. Requires
``pip install playwright`` and a Chromium build (``playwright install
chromium-headless-shell``).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SEEDED_RANDOM = """
(() => {
  let a = (window.__vgSeed >>> 0) || 1;
  Math.random = () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
})();
"""

# Installed before any page script: every clock the page can observe becomes
# virtual, and only __vgAdvance(ms) moves it.
VIRTUAL_CLOCK = """
(() => {
  const EPOCH = 1767225600000;  // 2026-01-01T00:00:00Z: pages never see the real date
  let now = 0;
  const RealDate = Date;
  class VirtualDate extends RealDate {
    constructor(...args) { if (args.length === 0) super(EPOCH + now); else super(...args); }
    static now() { return EPOCH + now; }
  }
  window.Date = VirtualDate;
  performance.now = () => now;
  if (document.timeline) {
    try { Object.defineProperty(document.timeline, "currentTime", { get: () => now }); } catch (e) {}
  }

  let frameQueue = [], frameId = 0;
  window.requestAnimationFrame = (callback) => { frameQueue.push([++frameId, callback]); return frameId; };
  window.cancelAnimationFrame = (id) => { frameQueue = frameQueue.filter((entry) => entry[0] !== id); };

  const timers = new Map();
  let timerId = 0;
  const schedule = (callback, ms, args, repeat) => {
    const id = ++timerId;
    const delay = Math.max(repeat ? 1 : 0, Number(ms) || 0);
    timers.set(id, { due: now + delay, callback, args, repeat: repeat ? delay : 0 });
    return id;
  };
  window.setTimeout = (callback, ms, ...args) => schedule(callback, ms, args, false);
  window.setInterval = (callback, ms, ...args) => schedule(callback, ms, args, true);
  window.clearTimeout = window.clearInterval = (id) => { timers.delete(id); };
  window.requestIdleCallback = (callback) => schedule(() => callback({ didTimeout: false, timeRemaining: () => 0 }), 0, [], false);
  window.cancelIdleCallback = window.clearTimeout;

  const started = new WeakMap();
  window.__vgAdvance = (target) => {
    let fired = 0;
    for (;;) {  // Timers fire in due order, each seeing its own due time.
      let next = null;
      for (const [id, timer] of timers) if (timer.due <= target && (!next || timer.due < next[1].due)) next = [id, timer];
      if (!next) break;
      if (++fired > 20000) throw new Error("timers keep rescheduling at the same instant");
      const [id, timer] = next;
      now = Math.max(now, timer.due);
      if (timer.repeat) timer.due += timer.repeat; else timers.delete(id);
      if (typeof timer.callback === "function") timer.callback(...timer.args);
    }
    now = target;
    const queue = frameQueue;
    frameQueue = [];
    for (const [, callback] of queue) callback(now);
    // CSS animations/transitions and WAAPI: pin each to virtual time since it appeared.
    for (const animation of document.getAnimations()) {
      if (!started.has(animation)) {
        started.set(animation, now - (animation.currentTime || 0));
        animation.pause();
      }
      animation.currentTime = (now - started.get(animation)) * (animation.playbackRate || 1);
    }
  };
})();
"""


VIRTUAL_AUDIO = """
(() => {
  // Web Audio becomes an OfflineAudioContext rendered in lockstep with the
  // virtual clock: ctx.currentTime equals virtual time, sounds are recorded.
  const SR = 48000, QUANTUM = 128 / SR;
  const Offline = window.OfflineAudioContext;
  if (!Offline) return;
  let audio = null;
  const quantise = (seconds) => Math.ceil(seconds / QUANTUM - 1e-9) * QUANTUM;
  function create() {
    if (audio) return audio.ctx;
    const startMs = performance.now();
    const seconds = Math.max(QUANTUM, window.__vgDuration - startMs / 1000);
    const ctx = new Offline({ numberOfChannels: 2, length: Math.ceil(seconds * SR), sampleRate: SR });
    audio = { ctx, startMs, rendered: 0, done: null, seconds };
    // AudioContext methods an offline context lacks or treats differently.
    ctx.resume = () => Promise.resolve();
    ctx.suspend = () => Promise.resolve();
    ctx.close = () => Promise.resolve();
    Object.defineProperty(ctx, "state", { get: () => "running" });
    ctx.createMediaElementSource = () => { throw new Error("VideoGenome capture cannot record media elements; use Web Audio nodes"); };
    ctx.createMediaStreamSource = ctx.createMediaElementSource;
    ctx.baseLatency = 0; ctx.outputLatency = 0;
    ctx.getOutputTimestamp = () => ({ contextTime: ctx.currentTime, performanceTime: performance.now() });
    return ctx;
  }
  const realSuspend = Offline.prototype.suspend, realResume = Offline.prototype.resume;
  function VirtualAudioContext() { return create(); }
  VirtualAudioContext.prototype = Offline.prototype;
  window.AudioContext = window.webkitAudioContext = VirtualAudioContext;
  // Render audio up to virtual time `ms` (called before the frame's callbacks run).
  window.__vgAudioTo = async (ms) => {
    if (!audio) return;
    const target = Math.min(audio.seconds, quantise((ms - audio.startMs) / 1000));
    if (target <= audio.rendered) return;
    const reached = realSuspend.call(audio.ctx, target);
    if (!audio.done) audio.done = audio.ctx.startRendering(); else realResume.call(audio.ctx);
    await reached;
    audio.rendered = target;
  };
  window.__vgAudioFinish = async () => {
    if (!audio) return null;
    if (!audio.done) audio.done = audio.ctx.startRendering(); else realResume.call(audio.ctx);
    const buffer = await audio.done;
    const left = buffer.getChannelData(0), right = buffer.getChannelData(buffer.numberOfChannels > 1 ? 1 : 0);
    const pcm = new Int16Array(left.length * 2);
    let peak = 0;
    for (let i = 0; i < left.length; i++) {
      const l = Math.max(-1, Math.min(1, left[i])), r = Math.max(-1, Math.min(1, right[i]));
      peak = Math.max(peak, Math.abs(l), Math.abs(r));
      pcm[2 * i] = l * 32767; pcm[2 * i + 1] = r * 32767;
    }
    const bytes = new Uint8Array(pcm.buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return { start_ms: audio.startMs, sample_rate: SR, peak, pcm: btoa(binary) };
  };
})();
"""

ORIGIN = "https://vg.local"
MIME = {".html": "text/html", ".htm": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
        ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
        ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg", ".mp4": "video/mp4", ".webm": "video/webm", ".wasm": "application/wasm",
        ".bin": "application/octet-stream", ".txt": "text/plain"}


def _served(root: Path, allowed: list[Path], libraries: dict[str, Path] | None = None):
    """Serve files under ``allowed`` from a virtual https origin; refuse everything else.

    Pages load from ``https://vg.local/<path relative to root>`` so ES modules,
    import maps and fetch() of sibling files work, while no request ever
    leaves the machine and nothing outside the allowed directories is readable.
    """
    def handler(route) -> None:
        url = route.request.url
        parsed = urlparse(url)
        if parsed.scheme in ("data", "blob"):
            route.continue_()
            return
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            route.abort()
            return
        relative = unquote(parsed.path).lstrip("/")
        base, scope = root, allowed
        head, _, rest = relative.partition("/")
        name, _, inner = rest.partition("/")
        if head == "_lib" and name in (libraries or {}):  # /_lib/<name>/... -> a shared library
            base, scope, relative = libraries[name], [libraries[name]], inner
        try:
            path = (base / relative).resolve()
        except (OSError, ValueError):
            route.abort()
            return
        if not path.is_file() or not any(path.is_relative_to(a) for a in scope):
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(status=200, body=path.read_bytes(),
                      headers={"Content-Type": MIME.get(path.suffix.lower(), "application/octet-stream"),
                               "Cache-Control": "no-store"})
    return handler


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    import wave
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def _open_page(browser, spec: dict, entry: Path, root: Path, allowed: list[Path],
               libraries: dict[str, Path], *, record_audio: bool = False):
    """A fresh page at the spec's size with the seeded, virtual-clock harness, loaded and set up.

    Returns ``(context, page, errors)``; ``errors`` collects every uncaught page error.
    """
    clock = spec.get("mode") == "clock"
    width, height = spec["width"], spec["height"]
    context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                  reduced_motion="no-preference")
    context.route("**/*", _served(root, allowed, libraries))
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    public = {k: spec[k] for k in ("params", "width", "height", "fps", "duration_seconds", "seed", "media")
              if k in spec}
    page.add_init_script(f"window.__vgSeed = {int(spec.get('seed', 0))};"
                         f"window.__vgDuration = {float(spec.get('duration_seconds', 0))};"
                         f"window.vgSpec = Object.freeze({json.dumps(public)});"
                         + SEEDED_RANDOM + (VIRTUAL_CLOCK if clock else "")
                         + (VIRTUAL_AUDIO if record_audio else ""))
    page.goto(f"{ORIGIN}/{entry.relative_to(root).as_posix()}", wait_until="load")
    if clock:
        page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
        if spec.get("click"):  # Pages that start on a click or tap ("click to play").
            x, y = spec["click"] if isinstance(spec["click"], list) else (width / 2, height / 2)
            page.mouse.click(x, y)
    else:
        page.evaluate("spec => window.vgSetup(spec)", spec)
    return context, page, errors


def _launch(playwright):
    return playwright.chromium.launch(args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
                                            "--autoplay-policy=no-user-gesture-required"])


def check(batch: Path, out: Path, samples: int = 12) -> None:
    """Load each page and step it through its duration without capturing frames.

    Recipes throw when copy cannot fit the frame; this surfaces those errors for
    every requested size in one browser session, in seconds rather than a render.
    ``batch`` is a JSON list of ``{"entry", "root", "allow", "lib", "spec"}``;
    ``out`` receives one ``{"error": str | null}`` per item.
    """
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    items = json.loads(batch.read_text(encoding="utf-8"))
    results = []
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        try:
            for item in items:
                spec = item["spec"]
                entry, root = Path(item["entry"]).resolve(), Path(item["root"]).resolve()
                allowed = [Path(a).resolve() for a in item.get("allow", [])] or [entry.parent]
                libraries = {name: Path(path).resolve() for name, path in item.get("lib", {}).items()}
                context, errors = None, []
                try:
                    if not entry.is_relative_to(root):
                        raise ValueError("entry must be inside the served root")
                    context, page, errors = _open_page(browser, spec, entry, root, allowed, libraries)
                    clock = spec.get("mode") == "clock"
                    frames = max(1, round(spec.get("duration_seconds", 1) * spec.get("fps", 24)))
                    for index in range(samples + 1):
                        if errors:
                            break
                        frame = min(frames - 1, round(index * (frames - 1) / samples))
                        ms = 1000 * frame / spec.get("fps", 24)
                        if clock:
                            page.evaluate("ms => window.__vgAdvance(ms)", ms)
                        else:
                            page.evaluate("([f, t]) => window.vgRender(f, t)", [frame, ms / 1000])
                except (PlaywrightError, ValueError) as exc:
                    errors.append(str(exc).splitlines()[0])
                finally:
                    if context is not None:
                        context.close()
                results.append({"error": errors[0] if errors else None})
        finally:
            browser.close()
    out.write_text(json.dumps(results), encoding="utf-8")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        parser = argparse.ArgumentParser()
        parser.add_argument("--check", type=Path, required=True, help="JSON list of pages to check")
        parser.add_argument("--out", type=Path, required=True)
        args = parser.parse_args()
        check(args.check, args.out)
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, help="Directory served as the virtual origin (default: the entry's)")
    parser.add_argument("--allow", type=Path, action="append", default=[],
                        help="Directory the page may load from (default: the entry's; repeatable)")
    parser.add_argument("--lib", action="append", default=[], metavar="NAME=DIR",
                        help="Serve a shared library at /_lib/NAME/ (repeatable)")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    frames = 1 if spec["media"] == "image" else max(1, round(spec["duration_seconds"] * fps))
    clock = spec.get("mode") == "clock"
    record_audio = clock and spec["media"] == "video" and spec.get("audio", False)
    # A still from a clock-driven page is taken at still_seconds (default: two thirds in).
    still_ms = 1000 * spec.get("still_seconds", 2 * spec.get("duration_seconds", 3) / 3)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("browser rendering needs `pip install playwright` and `playwright install chromium-headless-shell`")

    entry = args.entry.resolve()
    root = (args.root or entry.parent).resolve()
    allowed = [a.resolve() for a in args.allow] or [entry.parent]
    if not entry.is_relative_to(root):
        sys.exit("entry must be inside the served root")
    video_out = args.out.with_name(args.out.stem + ".picture.mp4") if record_audio else args.out
    if spec["media"] == "image":
        encode = ["-f", "image2pipe", "-c:v", "mjpeg", "-i", "-", "-frames:v", "1", str(args.out)]
    else:
        encode = ["-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(fps), "-i", "-",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p",
                  "-movflags", "+faststart", str(video_out)]
    captured = None
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        libraries = {name: Path(directory).resolve() for name, _, directory in
                     (item.partition("=") for item in args.lib)}
        context, page, errors = _open_page(browser, spec, entry, root, allowed, libraries,
                                           record_audio=record_audio)
        if errors:
            sys.exit(f"page setup failed: {errors[0]}")
        encoder = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *encode],
                                   stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        advance = ("async ms => { if (window.__vgAudioTo) await window.__vgAudioTo(ms); "
                   "window.__vgAdvance(ms); }")
        try:
            if clock and spec["media"] == "image":
                # Step up to the still's time so stateful animations evolve normally.
                step = 1000 / fps
                position = 0.0
                while position < still_ms:
                    page.evaluate(advance, position)
                    position += step
                times = [still_ms]
            else:
                times = [1000 * frame / fps for frame in range(frames)]
            for frame, ms in enumerate(times):
                if clock:
                    page.evaluate(advance, ms)
                else:
                    page.evaluate("([f, t]) => window.vgRender(f, t)", [frame, ms / 1000])
                # JPEG q100 capture is ~5x faster than PNG and visually lossless before H.264.
                encoder.stdin.write(page.screenshot(type="jpeg", quality=100, animations="allow",
                                                    clip={"x": 0, "y": 0, "width": width, "height": height}))
                if errors:
                    break
            if record_audio and not errors:
                captured = page.evaluate("async () => window.__vgAudioFinish ? await window.__vgAudioFinish() : null")
        finally:
            encoder.stdin.close()
            encoder.wait()
            browser.close()
    if errors:
        sys.exit(f"page raised in the browser: {errors[0]}")
    if encoder.returncode:
        sys.exit("ffmpeg failed to encode browser frames")
    if record_audio:
        _mux_audio(video_out, captured, args.out, spec)
        print("VG_AUDIO=" + ("recorded" if captured else "silent"))


def _mux_audio(picture: Path, captured: dict | None, output: Path, spec: dict) -> None:
    """Join the recorded Web Audio to the picture, delayed to when the page created its context."""
    import base64
    seconds = f"{spec['duration_seconds']:.6f}"
    if not captured:  # The page made no sound: write a silent track so the file shape is stable.
        command = ["-i", str(picture), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-map", "0:v:0", "-map", "1:a:0"]
    else:
        wav = output.with_name(output.stem + ".audio.wav")
        _write_wav(wav, base64.b64decode(captured["pcm"]), captured["sample_rate"])
        delay = max(0, round(captured["start_ms"]))
        command = ["-i", str(picture), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                   "-af", f"adelay={delay}:all=1,apad"]
    completed = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *command,
                                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", seconds,
                                "-movflags", "+faststart", str(output)], capture_output=True, text=True)
    picture.unlink(missing_ok=True)
    if captured:
        output.with_name(output.stem + ".audio.wav").unlink(missing_ok=True)
    if completed.returncode:
        sys.exit(f"ffmpeg failed to add the recorded audio: {completed.stderr[-600:]}")


if __name__ == "__main__":
    main()
