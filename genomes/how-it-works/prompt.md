# Authoring prompt: how-it-works system diagram

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that explains a system or process as a diagram that builds
itself, one part per beat.

**What the viewer sees.** A short kicker and a title rise in at the centre,
larger than they will finally sit, then glide up and settle as a header. The
diagram grows below it: each part of the system is a node (a card or circle
with a simple line icon drawn in code and a 1-3 word label). From the second
node on, an arrow draws itself out of the previous node and the next node
springs in exactly at its tip. Once an arrow is complete, small packets
stream along it so the flow is visible. Only one node is "current": it is
lit (accent ring, soft glow, filled icon disc) while a caption band below
explains it in one line, and earlier nodes dim back. The camera frames what
exists so far (zoomed in on the first node, pulling back as the system grows)
and never jumps. The final beat lights every node in a quick wave, speeds up
the packets and replaces the caption with a takeaway line. A loop variant
places the nodes on an ellipse and draws the closing arrow at the end.

**Layout.** Choose from node count and aspect ratio: a row in landscape
(up to four), a column in portrait (up to three), a snake grid for more, and
an ellipse for cycles. Share one label size across all nodes and one caption
size across all captions; shrink cards for crowded loops until nothing
overlaps, and throw if labels would fall below about `unit * 0.03`.

**Beat structure.** Intro about 13% of the duration (title), outro about 20%
(system lit plus takeaway), and equal beats for the nodes in between. Each
arrow draws in the 0.45 s before its node lands. Document the landing times
and the "system lit" time; templates cue clicks and a swell to them.

**Parameters.** `title`, `kicker`, `nodes` (2-6, maxLength 24), `captions`
(maxLength 72), `icons` (enum per node, `auto` for the node's number),
`takeaway`, `layout` (auto/row/column/snake/loop), a five-colour `palette`
(ground, ink, accent, flow, muted), `grid`, `packets`, `camera`, `grain`.
Ship four presets that read as different worlds (dark chalkboard, navy
blueprint, cream paper, terminal green).

**Rules.** Draw every string with `fillText`, fitted with `vg.fit`; pick ink
with `vg.readable` and tint lit cards only as far as their label keeps 4.5:1.
In 9:16 keep copy between 12% and 78% of the height. Bake static layers
(ground, grid, vignette) once and blit them; sample each arrow path once and
walk it by arc length. Seeded randomness only, no network.

**Checks.** Render every preset at 1080x1920 and 1920x1080 with the minimum
and maximum node counts and the longest labels, build contact sheets every
second and look at them: first node framed and centred, arrows reaching
their targets, no caption overlapping the next, every label legible, the lit
final frame. Then wire a template with a bed, clicks on the node landings
and a swell on the lit system, and confirm the loudness, true-peak and
no-dead-picture gates pass.
