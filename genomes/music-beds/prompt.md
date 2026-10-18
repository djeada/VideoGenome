# Authoring prompt: procedural music and sound

Build a new procedural music bed or sound effect: deterministic synthesis from a
seed with tempo, key, mode, energy and brightness params, mastered to -20 LUFS
so it sits under speech, with clean envelopes and no clipping. Check it with
loudness, band balance and a spectrogram, and listen before claiming it sounds
good.

**Structure.** Music beds are Python recipes (`runtime: python`) that write WAV
at 48 kHz with `kit.write_wav`. Build them from `dsp` and `instruments`: choose
a progression with `dsp.chord` and `dsp.voice_lead`, render parts with band-limited
oscillators and envelopes, place drums on a swing grid, add `dsp.reverb` sends,
and finish with `dsp.master(target_lufs=-20)`. Length must equal the requested
duration to the sample, with a musical ending or a clean fade. Expose `bpm`
(bounded), `key`, `mode`, `energy`, `brightness` and a few arrangement switches,
and ship presets named for moods. Document where the first downbeat lands so
scenes can sync to the tempo.
