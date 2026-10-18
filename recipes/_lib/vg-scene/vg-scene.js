// vg-scene: shared building blocks for VideoGenome scene recipes (MIT).
//
// A scene recipe is an HTML page that animates with ordinary timing APIs; the
// capture harness runs it on a virtual clock, so every frame is exact. Import:
//
//   import * as vg from "../../_lib/vg-scene/vg-scene.js";
//   const { spec, P, W, H } = vg.setup({ title: "Default title", palette: [...] });
//   const ctx = vg.canvas2d();
//   vg.loop((t) => { ... draw frame at t seconds ... });
//
// Rules this library helps keep: copy is drawn with fillText (never parsed as
// HTML), fitted with measured glyphs, and a page throws if copy cannot fit.

export const FONT = '"Inter", "Helvetica Neue", Arial, sans-serif';

// ---- spec and parameters ------------------------------------------------------
export function setup(defaults = {}, fallback = { width: 1920, height: 1080, duration_seconds: 8, seed: 1 }) {
  const spec = window.vgSpec || { ...fallback, params: {} };
  const P = Object.assign({}, defaults, spec.params || {});
  return { spec, P, W: spec.width, H: spec.height, D: spec.duration_seconds, unit: Math.min(spec.width, spec.height),
           portrait: spec.height > spec.width, seed: spec.seed || 1 };
}

export function canvas2d(id = "vg") {
  const spec = window.vgSpec || { width: 1920, height: 1080 };
  let canvas = document.getElementById(id);
  if (!canvas) { canvas = document.createElement("canvas"); canvas.id = id; document.body.appendChild(canvas); }
  canvas.width = spec.width; canvas.height = spec.height;
  document.documentElement.style.cssText = "margin:0;overflow:hidden;background:#000";
  document.body.style.cssText = "margin:0;overflow:hidden";
  canvas.style.display = "block";
  return canvas.getContext("2d");
}

// Calls draw(t, dt) every animation frame with t in seconds since the first frame.
export function loop(draw) {
  let start = null, last = 0;
  const step = (now) => {
    if (start === null) start = now;
    const t = (now - start) / 1000;
    draw(t, t - last);
    last = t;
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---- maths and easing ----------------------------------------------------------
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const invLerp = (a, b, x) => clamp((x - a) / (b - a));
export const smooth = (x) => x * x * (3 - 2 * x);
export const ease = {
  linear: (x) => x,
  outCubic: (x) => 1 - Math.pow(1 - x, 3),
  inCubic: (x) => x * x * x,
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  inExpo: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inOutExpo: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2),
  outBack: (x, c = 1.7) => 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2),
  inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
  outElastic: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI) / 3) + 1),
};
// Progress of a tween that starts at `start` seconds and lasts `duration`, eased.
export const tween = (t, start, duration, fn = ease.outCubic) => fn(clamp((t - start) / duration));
// Damped spring from 0 to 1 (overshoot set by damping, 0.2 = bouncy, 1 = critical).
export function spring(t, { stiffness = 10, damping = 0.35 } = {}) {
  if (t <= 0) return 0;
  const w = stiffness, z = clamp(damping, 0.01, 0.99), wd = w * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
}

// Seeded random numbers (mulberry32): use instead of Math.random for anything you
// want stable when parameters change (the harness also seeds Math.random).
export function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---- colour -----------------------------------------------------------------------
export function rgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}
export const rgba = (hex, a = 1) => { const [r, g, b] = rgb(hex); return `rgba(${r},${g},${b},${a})`; };
export function mix(a, b, t) {
  const x = rgb(a), y = rgb(b);
  return "#" + x.map((v, i) => Math.round(lerp(v, y[i], t)).toString(16).padStart(2, "0")).join("");
}
export function luminance(hex) {
  const c = rgb(hex).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
// The first candidate that reaches `ratio` against `background` (else the best one).
export function readable(background, candidates, ratio = 4.5) {
  const ok = candidates.find((c) => contrast(c, background) >= ratio);
  return ok || candidates.slice().sort((a, b) => contrast(b, background) - contrast(a, background))[0];
}

// ---- type ------------------------------------------------------------------------
export function font(ctx, size, weight = 700, family = FONT) {
  ctx.font = `${weight} ${Math.round(size)}px ${family}`;
  return ctx;
}

// Greedy word wrap at a measured width; null when a single word is too wide.
export function wrap(ctx, text, size, weight, maxWidth, maxLines = 99, family = FONT) {
  font(ctx, size, weight, family);
  const words = String(text).trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    if (ctx.measureText(word).width > maxWidth) return null;
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines.length <= maxLines ? lines : null;
}

// Largest size (stepping down from max) whose wrap fits width, line count and height;
// then rebalanced to the narrowest measure with the same line count (no orphans).
export function fit(ctx, text, { maxSize, minSize, weight = 700, maxWidth, maxLines = 3, maxHeight = Infinity,
                                 leading = 1.08, family = FONT, balance = true, label = "text" }) {
  const top = Math.max(Math.floor(maxSize), Math.ceil(minSize));
  for (let size = top; size >= Math.ceil(minSize); size -= 1) {
    let lines = wrap(ctx, text, size, weight, maxWidth, maxLines, family);
    if (!lines || lines.length * size * leading > maxHeight) continue;
    if (balance && lines.length > 1) {
      for (let w = maxWidth; w > maxWidth * 0.4; w -= Math.max(2, size * 0.1)) {
        const narrower = wrap(ctx, text, size, weight, w, lines.length, family);
        if (!narrower || narrower.length > lines.length) break;
        lines = narrower;
      }
    }
    const widths = lines.map((l) => { font(ctx, size, weight, family); return ctx.measureText(l).width; });
    return { size, lines, leading, weight, family, width: Math.max(...widths), height: lines.length * size * leading };
  }
  throw new Error(`${label} "${String(text).slice(0, 40)}" does not fit the layout; shorten it`);
}

// Draw a fitted block. align: left|center|right. y is the top of the block.
export function drawLines(ctx, block, x, y, { color = "#fff", align = "left", alpha = 1 } = {}) {
  font(ctx, block.size, block.weight, block.family);
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = color;
  ctx.globalAlpha = alpha;
  block.lines.forEach((line, i) => {
    const w = ctx.measureText(line).width;
    const lx = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
    ctx.fillText(line, lx, y + block.size * 0.78 + i * block.size * block.leading);
  });
  ctx.globalAlpha = 1;
}

// Format a number for display with fixed decimals and thousands separators.
export function formatNumber(value, decimals = 0, { prefix = "", suffix = "", separator = "," } = {}) {
  const fixed = Math.abs(value).toFixed(decimals);
  const [whole, frac] = fixed.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
  return `${value < 0 ? "-" : ""}${prefix}${grouped}${frac ? "." + frac : ""}${suffix}`;
}

// ---- texture ----------------------------------------------------------------------
let grainTile = null;
export function grain(ctx, t, amount = 0.04) {
  if (amount <= 0) return;
  if (!grainTile) {
    grainTile = document.createElement("canvas");
    grainTile.width = grainTile.height = 256;
    const g = grainTile.getContext("2d"), img = g.createImageData(256, 256), r = rng(9173);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = r() * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
  }
  const { width, height } = ctx.canvas;
  ctx.save();
  ctx.globalAlpha = amount; ctx.globalCompositeOperation = "overlay";
  ctx.translate(-Math.floor((t * 977) % 256), -Math.floor((t * 613) % 256));
  ctx.fillStyle = ctx.createPattern(grainTile, "repeat");
  ctx.fillRect(0, 0, width + 256, height + 256);
  ctx.restore();
}

export function vignette(ctx, strength = 0.35) {
  const { width: w, height: h } = ctx.canvas;
  const g = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.3, w / 2, h / 2, Math.hypot(w, h) / 1.7);
  g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, `rgba(0,0,0,${strength})`);
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
}

export function dotGrid(ctx, t, color, { spacing = 0.05, size = 0.0028, alpha = 0.18, drift = 0.12 } = {}) {
  const { width: w, height: h } = ctx.canvas, unit = Math.min(w, h), step = unit * spacing;
  const shift = (t * step * drift) % step;
  ctx.fillStyle = color; ctx.globalAlpha = alpha;
  for (let y = -step; y < h + step; y += step)
    for (let x = -step; x < w + step; x += step) ctx.fillRect(x + shift, y, unit * size, unit * size);
  ctx.globalAlpha = 1;
}

export function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr); ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr); ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

// Split [0, duration] into an intro, N equal beats and an outro; returns beat starts.
export function beats(duration, count, { intro = 0.8, outro = 1.2 } = {}) {
  const i = Math.min(intro, duration * 0.12), o = Math.min(outro, duration * 0.15);
  const beat = (duration - i - o) / Math.max(1, count);
  return { intro: i, outro: o, beat, start: (k) => i + k * beat, end: (k) => i + (k + 1) * beat, outroStart: duration - o };
}
