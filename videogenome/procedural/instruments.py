"""Reusable synthesized instruments for procedural music and sound design.

Every voice is mono float32 at :data:`dsp.SR`, starts with a short attack
ramp and ends with a fade (no clicks), and keeps partials below Nyquist (no
aliasing). Recipes pan, place and mix these with :mod:`dsp`. Randomness comes
only from the ``rng`` passed in, so arrangements stay deterministic.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from videogenome.procedural import dsp

SR = dsp.SR


def _ramp(sound: np.ndarray, attack: float = 0.002, release: float = 0.01) -> np.ndarray:
    """Click-free edges: short linear attack and cosine release."""
    n = len(sound)
    a = min(n, max(1, round(attack * SR)))
    r = min(n - a, max(1, round(release * SR))) if n > a else 0
    sound = sound.copy()
    sound[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if r > 0:
        sound[n - r:] *= np.cos(np.linspace(0, np.pi / 2, r, dtype=np.float32)) ** 2
    return sound


def _pitch_glide(start_hz: float, end_hz: float, n: int, seconds: float) -> np.ndarray:
    """Exponential pitch drop from start to end with time constant ``seconds``."""
    t = dsp.t_axis(n)
    return (end_hz + (start_hz - end_hz) * np.exp(-t / max(seconds, 1e-4))).astype(np.float32)


# ---------------------------------------------------------------- drums

def kick(velocity: float = 1.0, *, decay: float = 0.42, start_hz: float = 140.0, end_hz: float = 46.0,
         drop: float = 0.045, click: float = 0.25, rng: np.random.Generator | None = None) -> np.ndarray:
    """Round, soft kick: sine with an exponential pitch drop plus a tiny filtered click."""
    n = round((decay * 2.2) * SR)
    body = dsp.sine(_pitch_glide(start_hz, end_hz, n, drop), n)
    body *= np.exp(-dsp.t_axis(n) / decay)
    if click > 0:
        rng = rng or np.random.default_rng(0)
        tick = dsp.bandpass(rng.standard_normal(n).astype(np.float32), 1500, 6000)
        body += click * 0.35 * tick * np.exp(-dsp.t_axis(n) / 0.004)
    return _ramp(body * velocity, 0.001, 0.02)


def snare(velocity: float, rng: np.random.Generator, *, tone_hz: float = 185.0, decay: float = 0.16,
          brightness: float = 0.6) -> np.ndarray:
    """Noise snap (band-passed) over a two-partial tonal body."""
    n = round((decay * 2.5) * SR)
    t = dsp.t_axis(n)
    body = (np.sin(2 * np.pi * tone_hz * t) + 0.5 * np.sin(2 * np.pi * tone_hz * 1.78 * t))
    body *= np.exp(-t / (decay * 0.45))
    snap = dsp.bandpass(rng.standard_normal(n).astype(np.float32), 900, 3500 + 6000 * brightness)
    snap *= np.exp(-t / decay)
    return _ramp((0.45 * body + 0.9 * snap) * velocity, 0.001, 0.02)


def clap(velocity: float, rng: np.random.Generator, *, decay: float = 0.18) -> np.ndarray:
    """Three quick noise bursts then a short tail, band-passed around 1-5 kHz."""
    n = round((decay * 2.5 + 0.03) * SR)
    t = dsp.t_axis(n)
    envelope = np.zeros(n, dtype=np.float32)
    for offset in (0.0, 0.011, 0.023):
        start = round(offset * SR)
        envelope[start:] += np.exp(-(t[: n - start]) / 0.006)
    envelope += 0.6 * np.exp(-np.maximum(t - 0.023, 0) / decay) * (t >= 0.023)
    burst = dsp.bandpass(rng.standard_normal(n).astype(np.float32), 900, 5200) * envelope
    return _ramp(burst * velocity * 0.6, 0.0005, 0.02)


def hat(velocity: float, rng: np.random.Generator, *, decay: float = 0.045, cutoff: float = 7000.0,
        open_hat: bool = False) -> np.ndarray:
    """Hi-hat: high-passed noise plus a few inharmonic metallic partials."""
    decay = 0.28 if open_hat else decay
    n = round((decay * 3) * SR)
    t = dsp.t_axis(n)
    metal = sum(np.sin(2 * np.pi * f * t) for f in (3150.0, 4720.0, 6470.0, 8130.0)) / 4
    sound = dsp.highpass(rng.standard_normal(n).astype(np.float32) * 0.8 + 0.3 * metal, cutoff, order=2)
    sound *= np.exp(-t / decay)
    return _ramp(sound * velocity * 0.5, 0.0005, 0.01)


# ---------------------------------------------------------------- pitched

def electric_piano(note: int, seconds: float, velocity: float = 0.8, brightness: float = 0.5) -> np.ndarray:
    """Rhodes-like FM voice: 1:1 carrier/modulator with velocity-driven bark and a soft tine."""
    release = 0.25
    n = round((seconds + release) * SR)
    t = dsp.t_axis(n)
    freq = dsp.midi_to_hz(note)
    # Bark on the attack, then a sustained index so 2nd/3rd harmonics keep the body warm.
    index = (0.9 + 2.2 * brightness * velocity) * np.exp(-t / 0.35) + (0.7 + 0.8 * brightness) * np.exp(-t / 2.5)
    tone = np.sin(2 * np.pi * freq * t + index * np.sin(2 * np.pi * freq * t))
    if freq * 15 < SR * 0.45:  # Tine partial, only where it stays below Nyquist.
        tone += 0.12 * brightness * np.sin(2 * np.pi * freq * 14 * t) * np.exp(-t / 0.05)
    decay = 1.6 + 1.2 * (1 - (note - 48) / 48)
    envelope = np.exp(-t / max(decay, 0.6))
    hold = round(seconds * SR)
    if hold < n:
        envelope[hold:] *= np.exp(-np.linspace(0, 7, n - hold))
    # Gentle tremolo, like a vintage suitcase amp.
    tone *= 1 + 0.06 * np.sin(2 * np.pi * 4.6 * t)
    return _ramp((tone * envelope * velocity).astype(np.float32), 0.003, 0.02)


def pluck(note: int, seconds: float, velocity: float = 0.8, brightness: float = 0.5,
          decay: float = 0.6) -> np.ndarray:
    """Plucked synth: additive harmonics where higher partials die faster."""
    n = round((seconds + decay * 2) * SR)
    t = dsp.t_axis(n)
    freq = dsp.midi_to_hz(note)
    tone = np.zeros(n, dtype=np.float32)
    harmonics = 3 + round(10 * brightness)
    for k in range(1, harmonics + 1):
        if freq * k >= SR * 0.42:
            break
        tau = decay / (1 + 0.9 * (k - 1) * (1.2 - brightness))
        tone += (1 / k) * np.sin(2 * np.pi * freq * k * t) * np.exp(-t / tau)
    return _ramp(tone * velocity * 0.6, 0.002, 0.03)


def bass(note: int, seconds: float, velocity: float = 0.8, *, warmth: float = 0.5) -> np.ndarray:
    """Round electric-style bass: fundamental + soft odd harmonics, low-passed."""
    release = 0.08
    n = round((seconds + release) * SR)
    freq = dsp.midi_to_hz(note)
    t = dsp.t_axis(n)
    tone = np.sin(2 * np.pi * freq * t) + 0.22 * warmth * np.sin(2 * np.pi * freq * 2 * t) \
        + 0.12 * warmth * np.sin(2 * np.pi * freq * 3 * t)
    envelope = dsp.adsr(n, 0.008, 0.25, 0.7, release, hold=seconds)
    return _ramp(dsp.lowpass(tone * envelope, 420 + 500 * warmth) * velocity, 0.004, 0.03)


def sub(note: int, seconds: float, velocity: float = 0.8) -> np.ndarray:
    """Clean sine sub with a hint of second harmonic for small speakers."""
    release = 0.06
    n = round((seconds + release) * SR)
    freq = dsp.midi_to_hz(note)
    tone = dsp.sine(freq, n) + 0.15 * dsp.sine(freq * 2, n)
    return _ramp(tone * dsp.adsr(n, 0.01, 0.1, 0.9, release, hold=seconds) * velocity, 0.005, 0.03)


def pad(note: int, seconds: float, brightness: float, rng: np.random.Generator, *, release: float = 1.0,
        attack: float = 0.8) -> np.ndarray:
    """Soft detuned pad (three band-limited voices), low-passed by brightness."""
    n = round((seconds + release) * SR)
    freq = dsp.midi_to_hz(note)
    tone = np.zeros(n, dtype=np.float32)
    for cents in (-8.0, 0.0, 7.0):
        tone += dsp.additive(freq * 2 ** (cents / 1200), n, harmonics=4 + round(10 * brightness), tilt=1.2,
                             brightness=0.4 + brightness, phase_seed=int(rng.integers(1 << 30)))
    envelope = dsp.adsr(n, min(attack, seconds * 0.5), 0.6, 0.85, release, hold=seconds)
    return dsp.lowpass(tone * envelope / 3, 900 + 6000 * brightness)


# ---------------------------------------------------------------- texture and effects

def vinyl(n: int, rng: np.random.Generator, amount: float) -> np.ndarray:
    """Stereo vinyl texture: sparse band-limited crackle pops over soft hiss."""
    out = np.zeros((n, 2), dtype=np.float32)
    if amount <= 0:
        return out
    pops = rng.random(n) < (amount * 14 / SR)  # ~14 pops per second at full amount
    impulses = np.where(pops, rng.standard_normal(n) * rng.random(n) ** 2, 0.0).astype(np.float32)
    crackle = dsp.bandpass(impulses, 1200, 7000, order=2)
    hiss = dsp.bandpass(dsp.noise(n, rng, "pink"), 2000, 9000) * 0.06
    for channel in range(2):
        shift = 0 if channel == 0 else 37
        out[:, channel] = np.roll(crackle, shift) * 1.6 + hiss
    return out * amount


def tape_wow(stereo: np.ndarray, depth_ms: float, rate_hz: float = 0.55, flutter: float = 0.2) -> np.ndarray:
    """Slow pitch wobble by reading the signal through a modulated delay line."""
    if depth_ms <= 0:
        return stereo
    n = len(stereo)
    t = dsp.t_axis(n)
    offset = depth_ms / 1000 * SR * (np.sin(2 * np.pi * rate_hz * t)
                                     + flutter * np.sin(2 * np.pi * rate_hz * 7.3 * t + 1.1))
    positions = np.clip(np.arange(n, dtype=np.float64) - depth_ms / 1000 * SR * (1 + flutter) + offset, 0, n - 1)
    indices = np.arange(n, dtype=np.float64)
    return np.stack([np.interp(positions, indices, stereo[:, c]) for c in range(stereo.shape[1])],
                    axis=1).astype(np.float32)


def sweep_filter(x: np.ndarray, centres: np.ndarray, *, kind: str = "band", width: float = 1.0,
                 block: int = 256, order: int = 2) -> np.ndarray:
    """Time-varying filter: one centre frequency per block, state carried across blocks.

    ``kind`` is "band" (bandwidth = centre * width), "low" or "high".
    """
    blocks = max(1, int(np.ceil(len(x) / block)))
    centres = np.interp(np.linspace(0, 1, blocks), np.linspace(0, 1, len(centres)), centres)
    out = np.empty_like(x)
    zi = None
    for index in range(blocks):
        centre = float(np.clip(centres[index], 30, SR * 0.42))
        if kind == "band":
            low = max(20.0, centre / (1 + width / 2))
            high = min(SR * 0.45, centre * (1 + width / 2))
            sos = signal.butter(order, [low, high], "band", fs=SR, output="sos")
        else:
            sos = signal.butter(order, centre, "low" if kind == "low" else "high", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2, *x.shape[1:]), dtype=np.float64)
        chunk = x[index * block:(index + 1) * block]
        filtered, zi = signal.sosfilt(sos, chunk, axis=0, zi=zi)
        out[index * block:(index + 1) * block] = filtered
    return out.astype(np.float32)


def autopan(mono: np.ndarray, start: float, end: float, curve: np.ndarray | None = None) -> np.ndarray:
    """Constant-power pan that moves from ``start`` to ``end`` (-1..1) over the sound."""
    n = len(mono)
    progress = curve if curve is not None else np.linspace(0, 1, n, dtype=np.float32)
    position = start + (end - start) * progress
    angle = (position + 1) * np.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1).astype(np.float32)


def metallic(n: int, rng: np.random.Generator, base: float = 420.0, partials: int = 9) -> np.ndarray:
    """Inharmonic cymbal-like partial cluster mixed with high noise."""
    t = dsp.t_axis(n)
    ratios = [1.0, 1.47, 1.97, 2.53, 3.11, 3.81, 4.62, 5.37, 6.29][:partials]
    tone = sum(np.sin(2 * np.pi * base * r * t + rng.uniform(0, 2 * np.pi)) for r in ratios) / len(ratios)
    hiss = dsp.highpass(rng.standard_normal(n).astype(np.float32), 5000)
    return (0.5 * tone + 0.8 * hiss).astype(np.float32)


def strum_offsets(count: int, rng: np.random.Generator, spread: float = 0.018) -> list[float]:
    """Small, increasing onset offsets so chord notes roll like a human player."""
    return [i * spread + float(rng.uniform(0, spread * 0.4)) for i in range(count)]
