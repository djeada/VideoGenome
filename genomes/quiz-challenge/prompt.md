# Authoring prompt: quiz challenge short

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a beat-the-clock quiz of one to six questions that
share one set of two to four answers.

**What the viewer sees.** A hook that states the challenge and its stakes,
fully legible on frame 0 (a feed shows the first frame; it must already hook).
The answers sit at the bottom as big labelled targets in their own colours for
the whole video: that constant layout is what lets a viewer play along. Each
round: the question slams in at full width (it is the largest thing on
screen), a countdown the viewer can feel (a big digit that pops on each tick
inside a draining ring), and a reveal that hits: the right answer's colour
takes over the whole screen, the answer fills an empty slot above the
question, and a one-line reason or twist is held long enough to read. The
colour then wipes off, which is the cut to the next round. The outro recaps
every answer (a screenshot people save), asks for the viewer's score
(comments), ends on the call to action and fades back into the opening frame
so the short loops.

**Design for a thumb on a phone, not a screen recording.** The first version
of this class drew a tidy app UI: a small card, small dots, a small ring, a
box turning green on a dark ground. It read as a screenshot and nobody
watched. Size copy for a phone at arm's length (questions at full width,
nothing under ~3% of the short side), keep motion decisive (slam, flood, wipe,
punch-in on the reveal) and leave no stretch of the frame dead. The copy
matters more than the polish: a quiz people already know (das Mädchen) earns
no comments, a twist they do not (der See is a lake, die See is the sea) does.

**Beat structure.** Put every event on a musical beat grid set by a `bpm`
param and share it with the music bed: intro, rounds of a fixed number of
beats, ticks on sub-beats, the reveal on a downbeat. Document the frame of
every tick, reveal and exit, because the template cues sound to them.

**Parameters to expose.** `title`, `kicker`, `options`, `prompts`, `answers`,
optional `hints` and `notes` (all-or-none), `outro`, `cta`, `link`, an answer
style (tag or prefix, for articles), `palette`, `option_colors`, `bpm`, grain.
Ship at least three presets, light and dark.

**Rules.** Throw when an answer is not one of the options, when hints or notes
are given for only some questions, or when the duration cannot hold the
rounds. Fit copy with `vg.fit` and give every prompt one shared size, so the
reveal never resizes it and no round looks smaller. Keep copy out of the top
10% and bottom 20% in 9:16; lay a square out as its own shape. Fall back to
ink where an option colour would not read. Seeded randomness only, no network.

**Checks.** Render every preset in 9:16, 16:9 and 1:1, build contact sheets on
the beat events (each tick, the reveal, the reason, the exit, the outro) and
look at them. Then wire it into a template with ticks, a chime and a hit on
each reveal, a whoosh on each wipe and a pulse bed at the same tempo, and
confirm the loudness, true-peak and no-dead-picture gates pass in every
format.
