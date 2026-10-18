# Authoring prompt: animated chart with one takeaway

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) for a chart that tells exactly one point with two to eight
labelled values in a single unit.

**What the viewer sees.** The title states the point; under it a muted line
says what is measured, where and when. The baseline draws itself, then the
marks grow from zero in a quick stagger: horizontal bars in portrait (labels
in a right-aligned column, or above each bar when they are long), columns in
landscape, or a line that draws itself across the points with a glowing head
and a faint area wash. Values count up at the tips. A beat later the story
lands: every other mark recedes to grey, the key mark keeps the accent, a
light sheen runs along it, and its value grows. Then the takeaway rises in
beside an accent rule. The source sits at the foot of the frame throughout.

**Honesty rules.** Bars and columns start at zero. One series, one colour;
emphasis comes from recession, never from a rainbow. Label marks directly with
their values (a line labels its first, last and key points only). If a line
does not start at zero, show and label the range. Refuse negative values or
mismatched labels and values instead of drawing something misleading.

**Beat structure.** Make the beats independent of the number of values so
templates can lock sound cues: intro about 1 s, growth over about a quarter
of the duration, focus at about 45%, takeaway 0.7 s later. Publish them (for
example on `window.vgBeats`) and in the recipe header.

**Parameters to expose.** `labels` and `values` (arrays, 2-8, with a sentinel
for unused template slots), `title`, `subtitle`, `takeaway`, `source`,
`prefix`, `suffix`, `decimals`, `separator`, `highlight` (index, 0 for the
largest), `form` (auto, bars, columns, line), `sort`, `y_from_zero`, `tempo`,
`palette` (ground, ink, accent, muted), `grid`, `grain`; at least four
presets.

**Rules.** Fit every string with measured glyphs and one shared label size;
throw with a message that says what to shorten, never below about
`unit * 0.03`. Values and labels wear text colours, not the accent. Keep copy
out of the top 12% and bottom 22% in 9:16. Seeded randomness only, no network.

**Checks.** Render every preset in 9:16 and 16:9 with two, five and eight
values, long labels, a seven-digit value, a line that does not start at zero,
and a highlight that is not the largest; look at contact sheets every second.
Wire it into a template with verbatim labels, values, unit and source, a riser
under the growth and a click on the focus, and confirm the automated gates.
