# Authoring prompt: quiz challenge short

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a beat-the-clock quiz of one to six questions that
share one set of two to four answers.

**What the viewer sees.** A hook that states the challenge in the first frame
(words already rising on frame 0, so the video never opens on an empty
ground). The answers sit at the bottom as labelled targets in their own
colours for the whole video: that constant layout is what lets a viewer play
along. Each round: the question arrives with a physical motion (drop, slide,
flip), a countdown the viewer can feel (a ring, a bar, digits that pop on each
tick), a reveal that rewards (the right target fills, the wrong ones dim, a
short burst), the answer joined to the question, and a one-line reason held
long enough to read. The question then leaves into its answer, which is the
cut to the next round. The outro recaps every answer (a screenshot people
save), asks for the viewer's score (comments) and ends on the call to action.

**Beat structure.** Put every event on a musical beat grid set by a `bpm`
param and share it with the music bed: intro, rounds of a fixed number of
beats, ticks on sub-beats, the reveal on a downbeat. Document the frame of
every tick, reveal and exit, because the template cues sound to them.

**Parameters to expose.** `title`, `kicker`, `options`, `prompts`, `answers`,
optional `hints` and `notes` (all-or-none), `outro`, `cta`, `link`, an answer
style (tag or prefix, for articles), `palette`, `option_colors`, `bpm`, grain.
Ship at least three presets, light and dark.

**Rules.** Throw when an answer is not one of the options, when hints or
notes are given for only some questions, or when the duration cannot hold the
rounds. Fit copy with `vg.fit` and size each prompt once, with the answer in
place, so the reveal never resizes it. Keep copy out of the top 12% and
bottom 22% in 9:16; lay a square out as its own shape. Fall back to ink
where an option colour would not read. Seeded randomness only, no network.

**Checks.** Render every preset in 9:16, 16:9 and 1:1, build contact sheets on
the beat events (each tick, the reveal, the reason, the exit, the outro) and
look at them. Then wire it into a template with ticks, a chime on each reveal,
a whoosh on each exit and a pulse bed at the same tempo, and confirm the
loudness, true-peak and no-dead-picture gates pass in every format.
