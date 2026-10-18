# Authoring prompt: event teaser countdown

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a 10-15 second hype teaser for a dated event, made
first for 9:16 but working at 16:9 and 1:1.

**What the viewer sees.** Three acts. (1) Title: a kicker pill pops, then the
event name in a black display weight rises line by line through masks, as
large as fits, with an accent rule; a graphic motif (diagonal stripes,
pulsing rings or sliding bars) animates in beside or below it. (2) Countdown:
a three-band diagonal wipe cuts to three hard hits. In 3-2-1 mode each digit
slams from about 1.7x to 1x with fading ghost outlines, a ring, speed lines
and confetti, while the ground swaps colour through a circle that grows from
the centre. In days mode a slot-machine roll (odometer columns, motion blur,
feathered window) decelerates and locks exactly on the brief's number, with
its label landing on the middle hit. (3) Reveal: a second wipe opens on a
poster lockup: kicker, name, the date in an accent block that wipes open,
the place with a pin, and a call-to-action pill that pops and pulses gently
while the motif keeps moving.

**Beat structure.** Title about 28% of the duration (2.2-4 s), countdown hits
spaced about 8.5% apart, the reveal holding at least 2.5 s. Wipes switch the
scene at mid-wipe while the bands cover the frame. Document the wipe centres
and hit times so templates cue whooshes and impacts to them.

**Parameters.** event (32), date (30), place (40), kicker (24), cta (24),
count mode, days (integer), count label, `palette` (ground, ink, two
accents), motif, energy and grain. Ship at least four presets that each look
finished (dark neon, warm, aqua, light poster).

**Rules.** Draw copy with `fillText`, fit with `vg.fit` and shrink the reveal
lockup as a whole until it fits the safe band (below the top 12%, above the
bottom 22% in 9:16); throw if it still cannot. Choose every text colour with
`vg.readable` against the ground it sits on, including the accent grounds of
the countdown. Clip the motif to a region outside the copy's bounding box so
it never crosses text. Treat names, dates, places and numbers as facts:
never compute a day count. Seeded randomness only, no network.

**Checks.** Render every preset in both count modes at 1080x1920 and
1920x1080 for 12 s, with the longest and shortest copy; contact-sheet every
0.5 s and look at the wipes, each hit and the final frame. Wire it into a
template with a pulse bed, whooshes on wipes and impacts on hits; loudness,
true-peak and no-dead-picture gates must pass; human gates confirm the facts.
