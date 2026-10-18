# Authoring prompt: quote or lyric loop over generative art

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that sets one quote or lyric over a slow generative
backdrop and loops cleanly.

**What the viewer sees.** The backdrop is moving from the first frame: a field
that feels alive but never competes with the words, for example ribbons of
near-parallel streamlines through a seeded noise field, drifting out-of-focus
motes, or a soft gradient of a few large glows drawn at low resolution and
scaled up. A large opening quotation mark settles in the accent colour, then
the quote arrives phrase by phrase (break at punctuation; merge one-word
scraps; split runs longer than about seven words). Each word fades and rises a
little with a soft focus, and the next phrase starts only when the previous one
could have been read. After the last phrase an accent rule draws and the
attribution tracks in, then an optional source line in italic. Use a serif from
the system (a stack such as EB Garamond, Noto Serif, Georgia, serif); never
download a font.

**Loop.** Drive every backdrop motion by `theta = 2 * PI * t / D` with whole
numbers of cycles, and dissolve the copy over the last second, so the last
frame matches the first.

**Beat structure.** Opening mark around 0.3 s, first phrase near 0.9 s,
phrases at about 14 characters per second (at least 0.9 s each, slowed by at
most 15% to fill a long shot), a hold of at least two seconds with the
attribution, and the dissolve. If the quote cannot be read in the duration,
throw with the time it needs.

**Parameters to expose.** `quote` (maxLength about 140), `attribution`,
`source`, `backdrop` (enum), a four-colour `palette` (ground, ink, accent,
glow), `typeface` (serif, italic, sans), `align`, `tempo`, `motion`,
`density`, `scrim`, `loop`, `grain`. Ship at least four presets, dark and
light, and avoid the generic purple gradient.

**Rules.** Draw copy with `fillText`, never `innerHTML`. Typeset with measured
glyphs: largest size that fits, then line breaks that balance the measure and
prefer breaking after punctuation, and throw when it cannot fit. Keep a soft
pool of ground colour behind the copy so lines and motes never cross the text
at full strength, and pick ink with `vg.readable` (4.5:1). Lay out from `W`,
`H` and `unit`; in 9:16 keep copy out of the top 12% and bottom 22%. Seeded
randomness only, no network. Add grain so gradients never band.

**Checks.** Render every preset at 1080x1920, 1920x1080 and 1080x1080 with a
short and a 140-character quote, build contact sheets, and look at them: the
first frame (backdrop already alive), each phrase entering, the full hold, the
dissolve and the last frame. In the template, mark quote, attribution and
source `fill: "verbatim"`, add human gates for quote accuracy and for the
right to publish the words, and confirm the loudness and no-dead-picture gates
pass.
