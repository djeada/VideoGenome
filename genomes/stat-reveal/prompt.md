# Authoring prompt: headline stat reveal

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that reveals one to four headline statistics, each as the
hero of its own beat, for annual reports, impact reels and launch posts.

**What the viewer sees.** A heading at the top and a small source line at the
foot frame the piece from the first second. Each statistic then lands large:
its digits roll like an odometer (columns stop left to right, the rightmost
spins most) or count up from zero with the unit pinned so nothing jumps. A
currency sign and unit are set smaller in the accent colour. A meter fills in
step with the count, but only when the number is a share of a stated whole (a
percent is "of 100"); any other number gets a neutral frame, never a
proportion it does not have. The label rises through a line mask under or
beside the number. Between beats the hero slides up through a mask while the
meter unwinds; a recap closes with every number side by side. One focal point
per beat, no text jammed into corners, no everything-moves-at-once.

**Beat structure.** Intro about 0.9 s, an optional recap of about a fifth of
the duration, then equal beats; the count lasts about 45% of a beat. Publish
the entrance, landing and recap times (for example on `window.vgBeats`) and
write them in the recipe header, because templates cue risers to end and
impacts to hit on the landings.

**Parameters to expose.** `values` (numbers), `labels`, `prefixes`,
`suffixes`, `scales`, `decimals` (arrays of 1-4 with `maxItems`), `title`,
`source`, `meter` (ring, bar, none), `count` (roll, count), thousands
`separator`, `recap`, `tempo`, `palette` (ground, ink, accent, muted), `grid`
and `grain`. Ship at least four presets with distinct grounds.

**Rules.** Draw copy with `fillText`, fit labels with `vg.fit` and fit each
number block (prefix, digits, unit) by measuring it; throw when it cannot fit,
and never go below about `unit * 0.03`. Pick ink and muted text with
`vg.readable`; use the accent for text only when it clears 3:1 at display
size. Show decimals as the value is written. Lay out from `W`, `H` and
`unit`: in 9:16 stack the number over the label and keep copy out of the top
12% and bottom 22%; in 16:9 set them side by side and centre the group. Only
seeded randomness, no network.

**Checks.** Render every preset at 1080x1920 and 1920x1080 with one, three and
four statistics, short and long labels, a seven-digit number and a decimal;
build contact sheets every second and look at the landings, the exits, the
recap and the last frame. Wire it into a template whose numbers, units, labels
and source are `fill: "verbatim"`, and confirm loudness, true-peak and
no-dead-picture gates pass.
