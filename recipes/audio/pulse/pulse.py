"""Pulse: a modern, minimal tech/product bed.

Four-on-the-floor soft kick drives a sidechain pump on the pad and arpeggio,
a plucky arpeggio walks the chord tones through a ping-pong delay, an airy pad
holds the harmony and a clean sub follows the roots. ``energy`` adds offbeat
hats and a clap on 2 and 4. Rendered to exactly the requested duration.
"""
from __future__ import annotations

import math

import numpy as np

from videogenome.procedural import dsp, instruments as inst, kit


def arp_order(tones: list[int], pattern: str, steps: int, rng: np.random.Generator) -> list[int]:
    ladder = sorted(tones) + [t + 12 for t in sorted(tones)]
    if pattern == "up":
        cycle = ladder
    elif pattern == "down":
        cycle = ladder[::-1]
    elif pattern == "updown":
        cycle = ladder + ladder[-2:0:-1]
    else:  # "random" but seeded and melodic: random walk over the ladder.
        cycle, position = [], 0
        for _ in range(steps):
            position = int(np.clip(position + rng.choice([-2, -1, 1, 1, 2]), 0, len(ladder) - 1))
            cycle.append(ladder[position])
    return [cycle[i % len(cycle)] for i in range(steps)]


def render(spec: kit.Spec) -> None:
    p = spec.params
    rng = spec.rng
    seconds = spec.duration_seconds
    beat = 60 / p["bpm"]
    bar = 4 * beat
    chord_seconds = bar * p["bars_per_chord"]
    root = dsp.key_root(p["key"], octave=3)
    progression = p["progression"]
    chords = math.ceil(seconds / chord_seconds) + 1
    step = beat / (4 if p["arp_rate"] == "sixteenths" else 2)

    pad_bus = dsp.timeline(seconds + 3)
    arp_bus = dsp.timeline(seconds + 3)
    sub_bus = dsp.timeline(seconds + 3)
    drums = dsp.timeline(seconds + 3)
    voicing = None
    for index in range(chords):
        start = index * chord_seconds
        degree = progression[index % len(progression)]
        tones = dsp.chord(root, p["mode"], degree, size=4)
        voicing = dsp.voice_lead(voicing, tones, low=57, high=79)
        for position, note in enumerate(voicing):
            spread = (position / max(1, len(voicing) - 1) - 0.5) * 1.2
            dsp.place(pad_bus, dsp.pan(inst.pad(note, chord_seconds, p["brightness"], rng, release=0.9,
                                                attack=0.4), spread), start)
        arp_notes = arp_order([n + 12 for n in voicing[:3]], p["arp_pattern"], round(chord_seconds / step), rng)
        for k, note in enumerate(arp_notes):
            on_beat = (k * step) % beat < 1e-6
            if not on_beat and rng.random() > p["arp_density"]:
                continue
            velocity = (0.85 if on_beat else 0.6) * float(rng.uniform(0.85, 1.0))
            tone = inst.pluck(note, step * 0.9, velocity, p["brightness"], decay=0.25 + 0.3 * p["brightness"])
            dsp.place(arp_bus, dsp.pan(tone, float(rng.uniform(-0.35, 0.35))), start + k * step)
        sub_note = dsp.scale_note(root - 12, p["mode"], degree)
        while sub_note > 47:
            sub_note -= 12
        dsp.place(sub_bus, inst.sub(sub_note, chord_seconds - 0.02, 0.9), start)

    beats = math.ceil(seconds / beat) + 1
    for k in range(beats):
        time = k * beat
        dsp.place(drums, inst.kick(0.7, decay=0.26, start_hz=120, end_hz=50, click=0.4, rng=rng), time)
        if p["energy"] > 0.35:
            open_hat = k % 4 == 3
            hat = inst.hat((0.4 if open_hat else 0.6) * p["energy"] + 0.2, rng, cutoff=6000,
                           decay=0.11 if open_hat else 0.045)
            dsp.place(drums, dsp.pan(hat, 0.2), time + beat / 2)
        if p["energy"] > 0.6 and k % 2 == 1:
            dsp.place(drums, dsp.pan(inst.clap(0.7 * p["energy"], rng), -0.05), time)
        if p["energy"] > 0.8:
            for sixteenth in (1, 3):
                dsp.place(drums, dsp.pan(inst.hat(0.25, rng, cutoff=7000), -0.2), time + sixteenth * beat / 4)

    n = len(pad_bus)
    duck = dsp.pump(n, beat, depth=p["pump"], release=0.22)[:, None]
    arp_bus = dsp.delay(arp_bus, beat * 0.75, feedback=0.4, mix=0.3, repeats=5)
    music = dsp.reverb(0.5 * pad_bus * duck + 0.7 * arp_bus * (0.5 + 0.5 * duck),
                       seconds=2.2, mix=0.28, damping=8000, seed=spec.seed)
    sub_ducked = sub_bus * dsp.pump(n, beat, depth=min(0.9, p["pump"] + 0.2), release=0.18)[:, None]
    mix = music + 0.3 * sub_ducked + 0.7 * p["drums"] * drums
    mix = mix[: spec.samples]
    mastered = dsp.master(mix, peak_db=-1.0, fade_in=0.05, fade_out=min(2.5, seconds * 0.15), warmth=0.1,
                          target_lufs=-20.0)
    kit.write_wav(spec.output, mastered, spec.sample_rate)


if __name__ == "__main__":
    kit.run(render)
