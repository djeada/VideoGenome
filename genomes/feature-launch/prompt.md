# Authoring prompt: SaaS / app feature launch with a stylised UI

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
library `vg-scene`) that launches a software product in 14-24 seconds without
showing its real screens.

**What the viewer sees.** An app window drawn in code, not a screenshot: title
bar, sidebar or icon rail, a header with a primary button, KPI cards, a chart
widget, a list of toggles, an activity list and a notification toast. Draw
every "word" in the UI as a rounded skeleton bar, so nothing reads as a real
interface, number or claim. The window rises in tilted and settles at a hero
angle; its parts pop in with short staggers. A camera with real perspective
(draw the UI on its own canvas and move it with a CSS `matrix3d`, or use
WebGL) glides to one region per feature with an ease-in-out move, a slight
yaw towards the copy and a slow push while it holds. Beside each region a
numbered callout appears: a small index and rule, a bold headline rising
through a mask, one muted supporting line, joined to the exact UI point by a
curved leader that draws itself. A cursor hovers the chart (a tooltip pops),
clicks a toggle (press, ripple, knob slides on) and clicks the toast. The
camera pulls back, the window sinks to a tilted floor, and the product mark,
name and a call-to-action button land; the cursor clicks the button.

**Beat structure.** Intro about 11% of the duration, outro about 18%, the
rest split evenly among 1-3 features. Each feature: camera move first (about
1 s), callout from +0.55 s, out 0.25 s before the next move. Document the move
and click times, because templates cue whooshes and clicks to them.

**Parameters.** Product name (24), headlines (array of 1-3, 28 each), detail
lines (56), CTA (26), a disclaimer line such as "Illustrative interface",
`palette` (ground, surface, ink, accent), tilt, glow, grain, cursor on/off.
Ship at least three presets, dark and light.

**Rules.** Copy with `fillText` and `vg.fit` (one shared headline size;
throw when copy cannot fit). Ink from `vg.readable` (4.5:1), and put a ground
scrim behind callouts so text never sits on busy UI. Project UI points into
screen space each frame (`DOMMatrix.transformPoint`, divide by `w`) for
leaders and the cursor. Landscape: callouts beside the element, alternating
sides; portrait: below it, inside the 12%/78% safe band. Seeded randomness
only, no network. Keep the UI plane's resolution just above the closest
zoom and cache the window shadow; leave the background static.

**Checks.** Render every preset at 1080x1920 and 1920x1080 for 20 s, plus the
longest allowed copy; review contact sheets every second and full frames at
each callout. Wire it into a template with a pulse bed, whooshes on the moves
and soft clicks on the clicks; loudness, true-peak and no-dead-picture gates
must pass. Keep human gates for claims and for disclosing the mock UI.
