"""Lo-fi beat: a relaxed, swung hip-hop bed for code reels and tutorials.

Layers: synthesized drums (soft pitched kick, noise+tone snare, velocity-varied
hats on swung 16ths), jazz seventh/ninth chords on an FM electric piano with a
humanised strum, a root/fifth bass, vinyl crackle and a slow tape wobble, all
warmed by a gentle low-pass. Rendered to exactly the requested duration.
"""
from __future__ import annotations

import math

from videogenome.procedural import dsp, instruments as inst, kit

KICK_STEPS = (0, 7, 10)
SNARE_STEPS = (4, 12)


def step_time(bar_start: float, step: int, sixteenth: float, swing: float) -> float:
    """Swung 16th grid: odd 16ths are pushed late (swing 0.66 ~ triplet feel)."""
    late = swing * sixteenth * 0.5 if step % 2 else 0.0
    return bar_start + step * sixteenth + late


def render(spec: kit.Spec) -> None:
    p = spec.params
    rng = spec.rng
    seconds = spec.duration_seconds
    beat = 60 / p["bpm"]
    sixteenth = beat / 4
    bar = 4 * beat
    root = dsp.key_root(p["key"], octave=3)
    progression = p["progression"]
    bars = math.ceil(seconds / bar) + 1
    chord_size = 5 if p["extensions"] == "ninths" else 4

    drums = dsp.timeline(seconds + 3)
    keys = dsp.timeline(seconds + 3)
    low = dsp.timeline(seconds + 3)
    voicing = None
    for index in range(bars):
        start = index * bar
        degree = progression[index % len(progression)]
        tones = dsp.chord(root, p["mode"], degree, size=chord_size)
        # Rootless jazz voicing: the bass owns the root, keys play 3rd/5th/7th(/9th).
        voicing = dsp.voice_lead(voicing, tones[1:], low=55, high=77)

        # Keys: a soft strum on beat 1, a lighter re-hit on the "and" of 3 most bars.
        hits = [(0.0, bar * 0.62, 0.75)]
        if rng.random() < 0.7:
            hits.append((step_time(0, 10, sixteenth, p["swing"]), bar * 0.3, 0.5))
        for offset, length, velocity in hits:
            for position, (note, lag) in enumerate(zip(voicing, inst.strum_offsets(len(voicing), rng))):
                v = velocity * float(rng.uniform(0.85, 1.0))
                tone = inst.electric_piano(note, length, v, p["keys_brightness"])
                spread = (position / max(1, len(voicing) - 1) - 0.5) * 0.6
                dsp.place(keys, dsp.pan(tone, spread), start + offset + lag)

        # Bass: root on 1, fifth or octave pickup late in the bar.
        bass_root = dsp.scale_note(root - 12, p["mode"], degree)
        while bass_root > 52:
            bass_root -= 12
        dsp.place(low, inst.bass(bass_root, beat * 2.2, 0.85, warmth=p["warmth"]), start)
        pickup = bass_root + (7 if rng.random() < 0.6 else 12)
        dsp.place(low, inst.bass(pickup, beat * 0.9, 0.6, warmth=p["warmth"]),
                  step_time(start, 10, sixteenth, p["swing"]))

        # Drums, with small seeded variations so bars do not loop identically.
        for step in range(16):
            time = step_time(start, step, sixteenth, p["swing"])
            if step in KICK_STEPS or (step == 14 and rng.random() < 0.25):
                dsp.place(drums, inst.kick(0.9 if step == 0 else 0.7, rng=rng), time)
            if step in SNARE_STEPS:
                snap = inst.snare(0.85, rng, brightness=0.65)
                dsp.place(drums, dsp.pan(snap, 0.05), time)
            elif step % 2 == 1 and rng.random() < 0.12:  # ghost note
                dsp.place(drums, dsp.pan(inst.snare(0.18, rng, brightness=0.3), 0.05), time)
            if step % 2 == 0 and not (step == 8 and rng.random() < 0.15):
                accent = 1.0 if step % 4 == 0 else 0.7
                dsp.place(drums, dsp.pan(inst.hat(accent * float(rng.uniform(0.8, 1.1)), rng, cutoff=5200), 0.25), time)
            elif rng.random() < 0.18:
                dsp.place(drums, dsp.pan(inst.hat(0.4, rng, cutoff=5200), 0.25), time)

    keys = dsp.lowpass(keys, 3600 + 6500 * p["keys_brightness"])
    music = 1.0 * keys + 0.5 * low
    music = inst.tape_wow(music, depth_ms=0.6 * p["wobble"], rate_hz=0.5)
    music = dsp.reverb(music, seconds=1.8, mix=0.18 + 0.2 * p["room"], damping=5000, seed=spec.seed)
    drums = dsp.reverb(drums, seconds=0.9, mix=0.1 + 0.15 * p["room"], damping=7000, seed=spec.seed + 1)
    mix = music + p["drums"] * 0.75 * drums
    # Warmth: roll off the top like a worn tape, never muffled into mud.
    mix = dsp.lowpass(mix, 16000 - 6000 * p["warmth"], order=1)
    mix = mix[: spec.samples] + inst.vinyl(spec.samples, rng, p["crackle"])[: spec.samples]
    mastered = dsp.master(mix, peak_db=-1.0, fade_in=0.05, fade_out=min(2.5, seconds * 0.15),
                          warmth=0.1 + 0.2 * p["warmth"], target_lufs=-20.0)
    kit.write_wav(spec.output, mastered, spec.sample_rate)


if __name__ == "__main__":
    kit.run(render)
