# Authoring prompt: tempo-synced beat visualizer

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) whose shapes hit exactly on the beat of a music bed.

**Sync by tempo, not by listening.** A recipe cannot read the audio file. Take
`bpm`, `beats_per_bar` and `offset` (time of the first downbeat) as params,
and compute every hit from them: beat `k` lands at `offset + k * 60 / bpm`.
Read the audio recipe's code to see where its first kick lands
(`audio.pulse` places a kick at exactly `k * 60 / bpm` from 0 s, four on the
floor, claps on 2 and 4 at high energy, hats on the off-beat eighths). The
template must lock the same `bpm` into both recipes. Evaluate envelopes half
a frame late (`t + 0.5 / fps`) so each hit peaks on the frame nearest its
beat, and choose template tempos whose beat is a whole number of frames
(120 BPM at 30 fps is 15 frames).

**What the viewer sees.** A single focal form that reads as music: a core that
swells on the kick with ripples per beat, a mirrored equaliser whose low,
middle and top bands answer kick, backbeat and off-beats, or kinetic shapes
that snap a quarter turn per beat with overshoot. Accent every downbeat
(colour or size), show the bar (a filling arc or a lit marker per beat), and
keep some slow drift so the frame is alive between hits. Do not pretend the
bars are a spectrum analysis, and do not strobe: at most one soft full-frame
glow per beat, faster accents on small elements only.

**Copy.** A kicker, the title (show, mix, channel or event: never present the
procedural bed as a named artist's song) and a credit line, entering on the
first beats; with `loop` on they leave during the last bar so a whole number
of bars loops. Fit each with `vg.fit` (throws when it cannot fit), draw with
`fillText`, pick ink with `vg.readable`. In 9:16 keep copy between 12% and
78% of the height; in 16:9 set copy beside the visual, not in a corner.

**Parameters.** `title`, `credit`, `kicker` (with `maxLength`), `style`
(enum), `bpm`, `beats_per_bar`, `offset`, a four-colour `palette`,
`intensity`, `offbeat`, `loop`, `grain`. Ship at least three presets.

**Checks.** Render each preset at 1080x1920, 1920x1080 and 1080x1080 and look
at contact sheets. Then render the template and measure sync: detect kick
onsets in the decoded programme audio (low-band energy rise) and the frames
where the visual peaks (for example the area of the accent colour), and
report the offset in milliseconds. Confirm loudness, true peak,
no-dead-picture and no-silence gates pass.
