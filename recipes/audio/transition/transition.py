"""Transition: sound-design one-shots shaped to an exact duration.

Kinds: whoosh (band-passed noise sweeping up then down while panning across),
riser (noise plus a gliding tone that builds and peaks at the very end),
impact (low boom, body and noise burst near the start with a reverb tail),
swell (soft tonal-noise bloom peaking late), reverse_cymbal (a cymbal decay
played backwards into the cut) and soft_click (a small UI tick at the start).
Every kind renders exactly spec.duration_seconds so it lines up with a cut.
"""
from __future__ import annotations

import numpy as np

from videogenome.procedural import dsp, instruments as inst, kit


def bell_curve(n: int, peak: float, width: float) -> np.ndarray:
    x = np.linspace(0, 1, n, dtype=np.float32)
    return np.exp(-0.5 * ((x - peak) / max(width, 1e-3)) ** 2).astype(np.float32)


def whoosh(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    shape = bell_curve(n, 0.55, 0.2)
    source = dsp.noise(n, rng, "pink")
    centres = 300 + (1800 + 6000 * p["brightness"]) * shape[:: max(1, n // 400)]
    swept = inst.sweep_filter(source, centres, kind="band", width=1.2)
    mono = swept * shape
    progress = np.cumsum(shape) / max(1e-9, float(np.sum(shape)))
    motion = p["stereo_motion"]
    return inst.autopan(mono, -motion, motion, progress.astype(np.float32))


def riser(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    t = np.linspace(0, 1, n, dtype=np.float32)
    build = t ** 2.2
    start_hz = 110 * 2 ** (p["pitch"] / 12)
    freq = start_hz * 2 ** (3.0 * t ** 1.6)  # three-octave glide, accelerating
    tone = np.zeros(n, dtype=np.float32)
    phase = 2 * np.pi * np.cumsum(freq) / dsp.SR
    for k, amp in ((1, 1.0), (2, 0.4), (3, 0.25), (5, 0.12)):
        tone += amp * np.sin(k * phase) * (freq * k < dsp.SR * 0.42)
    air = inst.sweep_filter(dsp.noise(n, rng, "white"), 400 + (3000 + 9000 * p["brightness"]) * build[::max(1, n // 400)],
                            kind="low")
    mono = (0.55 * tone + 0.6 * air) * build
    motion = p["stereo_motion"]
    stereo = inst.autopan(mono, -0.2 * motion, 0.2 * motion)
    return dsp.widen(stereo, motion * build.mean())


def impact(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    hit = round(0.02 * dsp.SR)
    body_n = n - hit
    t = dsp.t_axis(body_n)
    boom_freq = 70 * 2 ** (p["pitch"] / 12)
    boom = dsp.sine(boom_freq * 0.5 + boom_freq * np.exp(-t / 0.08), body_n) * np.exp(-t / 0.55)
    thump = dsp.lowpass(rng.standard_normal(body_n).astype(np.float32), 900) * np.exp(-t / 0.05)
    crack = dsp.bandpass(rng.standard_normal(body_n).astype(np.float32), 1500, 4000 + 8000 * p["brightness"])
    crack *= np.exp(-t / 0.03)
    # Mid "body" so the hit still reads on phone speakers that cannot reproduce the boom.
    body = dsp.bandpass(rng.standard_normal(body_n).astype(np.float32), 180, 1400) * np.exp(-t / 0.12)
    mono = np.zeros(n, dtype=np.float32)
    mono[hit:] = 1.0 * boom + 0.45 * thump + 0.9 * body + 0.8 * crack
    return dsp.pan(mono, 0.0)


def swell(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    shape = bell_curve(n, 0.8, 0.22)
    root = 48 + p["pitch"]
    tone = sum(dsp.additive(dsp.midi_to_hz(root + interval), n, harmonics=6 + round(8 * p["brightness"]), tilt=1.3,
                            phase_seed=i) for i, interval in enumerate((0, 7, 12, 16)))
    air = dsp.bandpass(dsp.noise(n, rng, "pink"), 800, 3000 + 7000 * p["brightness"])
    mono = (0.35 * tone / 4 + 0.4 * air) * shape
    return dsp.widen(dsp.pan(mono, 0.0), 0.6 * p["stereo_motion"])


def reverse_cymbal(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    t = dsp.t_axis(n)
    cymbal = inst.metallic(n, rng, base=380 * 2 ** (p["pitch"] / 12))
    cymbal = dsp.highpass(cymbal, 1500 + 3000 * (1 - p["brightness"]))
    decay = np.exp(-t / max(0.15, n / dsp.SR * 0.35))
    mono = (cymbal * decay)[::-1].copy()
    stereo = inst.autopan(mono, -0.3 * p["stereo_motion"], 0.3 * p["stereo_motion"])
    return stereo


def soft_click(n: int, p: dict, rng: np.random.Generator) -> np.ndarray:
    length = min(n, round(0.035 * dsp.SR))
    t = dsp.t_axis(length)
    freq = 1800 * 2 ** (p["pitch"] / 12)
    blip = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.008)
    blip += 0.3 * dsp.bandpass(rng.standard_normal(length).astype(np.float32), 2000, 8000) * np.exp(-t / 0.003)
    mono = np.zeros(n, dtype=np.float32)
    mono[:length] = blip
    return dsp.pan(mono, 0.0)


KINDS = {"whoosh": whoosh, "riser": riser, "impact": impact, "swell": swell,
         "reverse_cymbal": reverse_cymbal, "soft_click": soft_click}


def render(spec: kit.Spec) -> None:
    p = spec.params
    n = spec.samples
    sound = KINDS[p["kind"]](n, p, spec.rng)
    if p["reverb"] > 0:
        size = 0.6 + 2.6 * p["reverb"]
        wet = dsp.reverb(sound, seconds=size, mix=1.0, damping=4000 + 6000 * p["brightness"], seed=spec.seed)
        if p["kind"] in ("riser", "reverse_cymbal", "swell"):
            # Build-ups should land on the cut, so the tail must not smear past it:
            # use pre-verb (reverb of the reversed sound, reversed back).
            wet = dsp.reverb(sound[::-1].copy(), seconds=size, mix=1.0, damping=6000, seed=spec.seed)[::-1]
        sound = (1 - 0.5 * p["reverb"]) * sound + 0.5 * p["reverb"] * wet
    sound = sound[:n]
    edge_out = 0.012 if p["kind"] in ("riser", "reverse_cymbal") else min(0.25, spec.duration_seconds * 0.2)
    # Loudness-normalise sustained effects; transient clicks (or anything under the
    # 0.4 s BS.1770 block) are peak-normalised instead so they stay subtle.
    long_enough = spec.duration_seconds >= 0.4 and p["kind"] != "soft_click"
    peak = -1.0 if long_enough else (-6.0 if p["kind"] == "soft_click" else -3.0)
    mastered = dsp.master(sound, peak_db=peak, fade_in=0.002, fade_out=edge_out,
                          warmth=0.05, target_lufs=-18.0 if long_enough else None)
    kit.write_wav(spec.output, mastered, spec.sample_rate)


if __name__ == "__main__":
    kit.run(render)
