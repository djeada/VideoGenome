"""Audio building blocks for procedural music and sound design (numpy + scipy).

Everything works on float32 arrays at :data:`SR`; stereo signals are (n, 2).
Recipes compose these into instruments and arrangements; no samples, no
third-party audio, fully deterministic for a given seed.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from videogenome.procedural.kit import SAMPLE_RATE as SR

NOTE_NAMES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
              "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10], "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10], "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9], "minor_pentatonic": [0, 3, 5, 7, 10],
}


# ---------------------------------------------------------------- theory

def midi_to_hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def key_root(key: str, octave: int = 3) -> int:
    if key not in NOTE_NAMES:
        raise ValueError(f"unknown key {key!r}")
    return 12 * (octave + 1) + NOTE_NAMES[key]


def scale_note(root: int, mode: str, degree: int) -> int:
    """MIDI note of a 1-based scale degree; degrees past the scale wrap upward."""
    steps = SCALES[mode]
    index = degree - 1
    return root + 12 * (index // len(steps)) + steps[index % len(steps)]


def chord(root: int, mode: str, degree: int, size: int = 4) -> list[int]:
    """Diatonic chord stacked in thirds (size 3 = triad, 4 = seventh, 5 = ninth)."""
    return [scale_note(root, mode, degree + 2 * i) for i in range(size)]


def voice_lead(previous: list[int] | None, notes: list[int], low: int = 52, high: int = 76) -> list[int]:
    """Move chord tones by octaves to stay close to the previous voicing and in range."""
    voiced = []
    for note in notes:
        while note < low:
            note += 12
        while note > high:
            note -= 12
        if previous:
            centre = sum(previous) / len(previous)
            while note - centre > 7 and note - 12 >= low:
                note -= 12
            while centre - note > 7 and note + 12 <= high:
                note += 12
        voiced.append(note)
    return sorted(set(voiced))


# ---------------------------------------------------------------- signals

def timeline(seconds: float) -> np.ndarray:
    return np.zeros((max(1, round(seconds * SR)), 2), dtype=np.float32)


def t_axis(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float32) / SR


def sine(freq: float | np.ndarray, n: int, phase: float = 0.0) -> np.ndarray:
    if np.ndim(freq):
        return np.sin(2 * np.pi * np.cumsum(freq) / SR + phase).astype(np.float32)
    return np.sin(2 * np.pi * freq * t_axis(n) + phase).astype(np.float32)


def additive(freq: float, n: int, harmonics: int = 24, tilt: float = 1.0, odd_only: bool = False,
             phase_seed: int = 0, brightness: float = 1.0) -> np.ndarray:
    """Band-limited saw/square-like tone: harmonic k has amplitude k**-tilt."""
    t = t_axis(n)
    rng = np.random.default_rng(phase_seed)
    out = np.zeros(n, dtype=np.float32)
    for k in range(1, harmonics + 1):
        if odd_only and k % 2 == 0:
            continue
        if freq * k >= SR / 2 * 0.9:
            break
        rolloff = np.exp(-(k - 1) / max(0.5, 6 * brightness))
        out += (rolloff / k ** tilt) * np.sin(2 * np.pi * freq * k * t + rng.uniform(0, 2 * np.pi))
    return out / max(1e-6, np.max(np.abs(out)))


def noise(n: int, rng: np.random.Generator, color: str = "white") -> np.ndarray:
    white = rng.standard_normal(n).astype(np.float32)
    if color == "white":
        return white
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    freqs[0] = freqs[1]
    spectrum /= np.sqrt(freqs) if color == "pink" else freqs
    out = np.fft.irfft(spectrum, n).astype(np.float32)
    return out / max(1e-6, np.max(np.abs(out)))


def adsr(n: int, attack: float, decay: float, sustain: float, release: float, hold: float | None = None) -> np.ndarray:
    """Envelope for n samples; release starts at ``hold`` seconds (default: n - release)."""
    a, d, r = (max(1, round(x * SR)) for x in (attack, decay, release))
    hold_samples = n - r if hold is None else min(n, round(hold * SR))
    env = np.full(n, sustain, dtype=np.float32)
    env[:min(a, n)] = np.linspace(0, 1, a, dtype=np.float32)[:min(a, n)]
    if a < n:
        seg = min(d, n - a)
        env[a:a + seg] = np.linspace(1, sustain, d, dtype=np.float32)[:seg]
    if hold_samples < n:
        start_level = env[max(0, hold_samples - 1)]
        tail = n - hold_samples
        env[hold_samples:] = start_level * np.exp(-np.linspace(0, 6, tail, dtype=np.float32))
    return env


def exp_decay(n: int, seconds: float) -> np.ndarray:
    return np.exp(-t_axis(n) / max(seconds, 1e-4)).astype(np.float32)


# ---------------------------------------------------------------- filters

def lowpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, min(cutoff, SR * 0.45), "low", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


def highpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, max(cutoff, 10), "high", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


def bandpass(x: np.ndarray, low: float, high: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, [max(low, 10), min(high, SR * 0.45)], "band", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


def sweep_lowpass(x: np.ndarray, start: float, end: float, block: int = 512, order: int = 2) -> np.ndarray:
    """Time-varying low-pass (exponential cutoff sweep), processed in blocks with state carry."""
    out = np.empty_like(x)
    blocks = max(1, int(np.ceil(len(x) / block)))
    cutoffs = np.geomspace(max(start, 20), max(end, 20), blocks)
    zi = None
    for index in range(blocks):
        sos = signal.butter(order, min(cutoffs[index], SR * 0.45), "low", fs=SR, output="sos")
        chunk = x[index * block:(index + 1) * block]
        if zi is None:  # Filter state: (sections, 2[, channels]); carried across blocks.
            zi = np.zeros((sos.shape[0], 2, *x.shape[1:]), dtype=np.float64)
        filtered, zi = signal.sosfilt(sos, chunk, axis=0, zi=zi)
        out[index * block:(index + 1) * block] = filtered
    return out.astype(np.float32)


# ---------------------------------------------------------------- space

def pan(mono: np.ndarray, position: float) -> np.ndarray:
    """Constant-power pan, position -1 (left) .. 1 (right)."""
    angle = (position + 1) * np.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1).astype(np.float32)


def reverb(x: np.ndarray, seconds: float = 2.4, mix: float = 0.25, damping: float = 6000,
           predelay: float = 0.02, seed: int = 0) -> np.ndarray:
    """Stereo convolution reverb with a synthetic, decorrelated decaying-noise impulse."""
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    rng = np.random.default_rng(seed)
    n = max(1, round(seconds * SR))
    decay = np.exp(-6.9 * t_axis(n) / seconds)
    impulse = np.stack([lowpass(rng.standard_normal(n).astype(np.float32), damping) * decay,
                        lowpass(rng.standard_normal(n).astype(np.float32), damping) * decay], axis=1)
    impulse[: round(predelay * SR)] = 0
    impulse /= np.sqrt(np.sum(impulse ** 2, axis=0, keepdims=True)) + 1e-9
    wet = np.stack([signal.fftconvolve(x[:, c], impulse[:, c])[: len(x)] for c in range(2)], axis=1)
    return ((1 - mix) * x + mix * wet).astype(np.float32)


def delay(x: np.ndarray, seconds: float, feedback: float = 0.35, mix: float = 0.25, repeats: int = 6,
          ping_pong: bool = True) -> np.ndarray:
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    out = x.copy()
    step = round(seconds * SR)
    for k in range(1, repeats + 1):
        if step * k >= len(x):
            break
        gain = mix * feedback ** (k - 1)
        shifted = np.zeros_like(x)
        shifted[step * k:] = x[: len(x) - step * k]
        if ping_pong:
            shifted = shifted[:, ::-1] if k % 2 else shifted
        out += gain * shifted
    return out


def widen(stereo: np.ndarray, amount: float) -> np.ndarray:
    mid = (stereo[:, 0] + stereo[:, 1]) / 2
    side = (stereo[:, 0] - stereo[:, 1]) / 2 * (1 + amount)
    return np.stack([mid + side, mid - side], axis=1).astype(np.float32)


# ---------------------------------------------------------------- arrangement

def place(track: np.ndarray, sound: np.ndarray, start_seconds: float, gain: float = 1.0) -> None:
    """Mix ``sound`` (mono or stereo) into ``track`` at a time, clipping at the end."""
    start = round(start_seconds * SR)
    if start >= len(track):
        return
    if sound.ndim == 1:
        sound = np.stack([sound, sound], axis=1)
    end = min(len(track), start + len(sound))
    track[start:end] += gain * sound[: end - start]


def pump(n: int, beat_seconds: float, depth: float = 0.5, release: float = 0.25) -> np.ndarray:
    """Sidechain-style gain curve that dips on every beat and recovers smoothly."""
    phase = (t_axis(n) % beat_seconds) / beat_seconds
    return (1 - depth * np.exp(-phase / max(release, 1e-3))).astype(np.float32)


def loudness_lufs(stereo: np.ndarray) -> float:
    """Integrated loudness per ITU-R BS.1770-4 (K-weighting, 400 ms blocks, gating)."""
    if stereo.ndim == 1:
        stereo = np.stack([stereo, stereo], axis=1)
    # K-weighting: high-shelf (+4 dB above ~1.5 kHz) then RLB high-pass (~38 Hz), at 48 kHz.
    shelf = signal.tf2sos([1.53512485958697, -2.69169618940638, 1.19839281085285],
                          [1.0, -1.69065929318241, 0.73248077421585])
    rlb = signal.tf2sos([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
    weighted = signal.sosfilt(np.vstack([shelf, rlb]), stereo, axis=0)
    block, hop = round(0.4 * SR), round(0.1 * SR)
    if len(weighted) < block:
        return float("-inf")
    starts = range(0, len(weighted) - block + 1, hop)
    powers = np.array([np.sum(np.mean(weighted[s:s + block] ** 2, axis=0)) for s in starts])
    loud = powers[powers > 10 ** ((-70 + 0.691) / 10)]
    if not len(loud):
        return float("-inf")
    relative = 10 * np.log10(np.mean(loud)) - 0.691 - 10
    gated = loud[-0.691 + 10 * np.log10(loud) > relative]
    return float(-0.691 + 10 * np.log10(np.mean(gated))) if len(gated) else float("-inf")


def band_energy(stereo: np.ndarray) -> dict[str, float]:
    """Share of spectral energy per band, a quick proxy for tonal balance."""
    mono = stereo.mean(axis=1) if stereo.ndim > 1 else stereo
    power = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    bands = {"sub": (20, 60), "low": (60, 250), "low_mid": (250, 1000), "mid": (1000, 4000),
             "high": (4000, 10000), "air": (10000, 20000)}
    total = power[(freqs >= 20) & (freqs < 20000)].sum() or 1.0
    return {name: round(float(power[(freqs >= lo) & (freqs < hi)].sum() / total), 3)
            for name, (lo, hi) in bands.items()}


def master(mix: np.ndarray, *, peak_db: float = -1.0, fade_in: float = 0.05, fade_out: float = 2.0,
           warmth: float = 0.15, target_lufs: float | None = -20.0) -> np.ndarray:
    """High-pass rumble, gentle saturation, fades, then loudness target under a peak ceiling.

    Beds default to -20 LUFS so they sit under speech; the programme master
    (FFmpeg loudnorm) sets final delivery loudness.
    """
    mix = highpass(mix, 28, order=2)
    if warmth > 0:
        drive = 1 + 3 * warmth
        mix = np.tanh(mix * drive) / np.tanh(drive)
    n = len(mix)
    envelope = np.ones(n, dtype=np.float32)
    fi, fo = min(n, round(fade_in * SR)), min(n, round(fade_out * SR))
    if fi:
        envelope[:fi] = np.linspace(0, 1, fi) ** 2
    if fo:
        envelope[n - fo:] = np.minimum(envelope[n - fo:], np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)
    mix = mix * envelope[:, None]
    peak = np.max(np.abs(mix)) or 1.0
    gain = 10 ** (peak_db / 20) / peak
    if target_lufs is not None:
        measured = loudness_lufs(mix)
        if np.isfinite(measured):
            gain = min(gain, 10 ** ((target_lufs - measured) / 20))
    return (mix * gain).astype(np.float32)
