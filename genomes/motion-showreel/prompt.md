# Authoring prompt: motion design showreel

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a 12-18 second abstract motion-design reel that shows
craft, not stock effects.

**What the viewer sees.** Five or six beats, each with one focal point and a
designed hand-off into the next, in a five-colour palette (ground, ink and three
brand colours). A good set: a dot grid that ripples and then springs into a
disc; that disc morphing through shapes on springs (sample each shape as a
radius per angle and interpolate, so overshoot is free) with colour echoes and
orbiting satellites; an iris that opens into the first word, which rises letter
by letter through a mask; a staggered diagonal stripe wipe; circular kinetic
type (the second word running round a rotating ring around a sprung disc that
holds it); a two-tone mask sweep over the third word; shutters closing into the
name, which lands with an impact ring, three sprung shapes and a tracked kicker.
Hold every word at least 1.5 s and the name about 2.5 s.

**Motion grammar.** Springs (`vg.spring`) for anything that lands, outExpo or
inOutExpo for wipes and irises, staggers of 20-90 ms for letters and shapes,
anticipation before cuts, nothing moving at once except during transitions. No
generic gradients, no jammed corners, no strobing.

**Beat structure.** Design at 15 s and scale every time by D / 15; document the
morph pops, wipes, irises, shutters and the name impact, because templates cue
clicks, whooshes, a riser and an impact to them.

**Parameters to expose.** `name` (maxLength 24), `words` (exactly three, 16
characters each), `kicker`, `palette`, `grid`, `grain`. Ship four presets with
distinct characters (bold primary, monochrome with one accent, acid, paper).

**Rules.** Fit every word and the name with `vg.fit` and throw when it cannot
fit; choose ink per ground with `vg.readable`; lay out from `W`, `H` and `unit`
so 16:9, 9:16 and 1:1 work; seeded randomness only; no network.

**Checks.** Render every preset at 1920x1080 and 1080x1920 with short and
16-character words and a two-line name; build contact sheets every 1.25 s plus a
dense sheet across each transition; confirm no blank frames; then make the
template with a pulse bed and pass the automated gates.
