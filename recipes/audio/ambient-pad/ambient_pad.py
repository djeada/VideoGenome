"""Ambient pad: a slow, voice-led chord progression for narration beds.

Layers: detuned band-limited pads (voice-led diatonic sevenths), a soft sub
bass on the chord root, sparse FM-bell sparkles through a ping-pong delay,
and a faint air layer, all into a stereo convolution reverb. The piece is
rendered to exactly the requested duration and ends with a natural fade.
"""
from __future__ import annotations

import math

import numpy as np

from videogenome.procedural import dsp, kit


def pad_note(note: int, seconds: float, release: float, brightness: float, rng: np.random.Generator) -> np.ndarray:
    n = round((seconds + release) * dsp.SR)
    freq = dsp.midi_to_hz(note)
    harmonics = 4 + round(10 * brightness)
    tone = np.zeros(n, dtype=np.float32)
    for cents in (-7.0, 0.0, 6.0):  # Three detuned voices for width and movement.
        detuned = freq * 2 ** (cents / 1200)
        tone += dsp.additive(detuned, n, harmonics=harmonics, tilt=1.1, brightness=0.4 + brightness,
                             phase_seed=int(rng.integers(1 << 30)))
    attack = min(1.6, seconds * 0.45)
    envelope = dsp.adsr(n, attack, 0.8, 0.85, release, hold=seconds)
    return dsp.lowpass(tone * envelope / 3, 1200 + 6500 * brightness, order=2)


def bell(note: int, rng: np.random.Generator) -> np.ndarray:
    n = round(2.4 * dsp.SR)
    t = dsp.t_axis(n)
    freq = dsp.midi_to_hz(note)
    index = 2.2 * np.exp(-t / 0.35)
    tone = np.sin(2 * np.pi * freq * t + index * np.sin(2 * np.pi * freq * 3.5 * t))
    tone += 0.25 * np.sin(2 * np.pi * freq * 2.0 * t) * np.exp(-t / 0.6)
    envelope = np.exp(-t / 0.9) * np.minimum(1, t / 0.004)
    return (tone * envelope * rng.uniform(0.6, 1.0)).astype(np.float32)


def render(spec: kit.Spec) -> None:
    p = spec.params
    rng = spec.rng
    seconds = spec.duration_seconds
    beat = 60 / p["bpm"]
    chord_seconds = p["bars_per_chord"] * 4 * beat
    root = dsp.key_root(p["key"], octave=3)
    progression = p["progression"]
    count = math.ceil(seconds / chord_seconds) + 1

    pads = dsp.timeline(seconds + 4)
    bass = dsp.timeline(seconds + 4)
    bells = dsp.timeline(seconds + 4)
    voicing = None
    for index in range(count):
        degree = progression[index % len(progression)]
        start = index * chord_seconds
        voicing = dsp.voice_lead(voicing, dsp.chord(root, p["mode"], degree, size=4), low=57, high=81)
        for position, note in enumerate(voicing):
            spread = (position / max(1, len(voicing) - 1) - 0.5) * 2 * p["width"]
            dsp.place(pads, dsp.pan(pad_note(note, chord_seconds, 1.4, p["brightness"], rng), spread), start)
        bass_note = dsp.scale_note(root - 12, p["mode"], degree)
        n = round((chord_seconds + 0.8) * dsp.SR)
        tone = dsp.sine(dsp.midi_to_hz(bass_note), n) + 0.18 * dsp.sine(dsp.midi_to_hz(bass_note + 12), n)
        dsp.place(bass, dsp.lowpass(tone * dsp.adsr(n, 0.4, 0.5, 0.9, 0.8, hold=chord_seconds), 220), start)
        steps = round(chord_seconds / (beat / 2))
        for step in range(steps):
            if rng.random() < p["sparkle"] * 0.32:
                note = int(rng.choice(voicing)) + 12 * int(rng.integers(1, 3))
                dsp.place(bells, dsp.pan(bell(note, rng), float(rng.uniform(-0.7, 0.7))),
                          start + step * beat / 2)

    bells = dsp.delay(bells, beat * 0.75, feedback=0.45, mix=0.35, repeats=5)
    air = dsp.bandpass(dsp.noise(len(pads), rng, "pink"), 4000, 12000)[:, None] * np.ones((1, 2))
    space = dsp.reverb(0.55 * pads + 0.5 * bells + 0.03 * p["air"] * air,
                       seconds=2.5 + 3 * p["reverb"], mix=0.2 + 0.4 * p["reverb"], seed=spec.seed)
    # Low end stays supportive: a sub you feel, not a drone that masks speech.
    mix = space + 0.16 * p["bass"] * dsp.highpass(bass, 45)
    mix = mix[: spec.samples]
    mastered = dsp.master(mix, peak_db=-1.0, fade_in=0.6, fade_out=min(3.0, seconds * 0.2), warmth=p["warmth"])
    kit.write_wav(spec.output, mastered, spec.sample_rate)


if __name__ == "__main__":
    kit.run(render)
