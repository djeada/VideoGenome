# Authoring prompt: 3D product hero (stylised stand-in)

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
libraries `vg-scene` and `three`) for a premium studio product shot rendered
with the vendored Three.js on software WebGL.

**What the viewer sees.** One product on a seamless studio floor. It starts as
a rim-lit silhouette, then a key light sweeps on so a highlight travels across
it. The camera makes one confident move (an orbit of about 70 degrees, a push
from wide to hero, or a pull back from a macro detail) and lands by about 55%
of the shot, then drifts. The product name rises word by word beside it
(left column in 16:9, below it in 9:16 and 1:1), then a one-line tagline and a
call-to-action pill. A small footnote says the image is an illustrative render.

**Honesty.** The product is a generic stand-in built from primitives (lathe
profiles for bottles, cans and jars, rounded boxes, extruded slabs) with the
name printed on a canvas-texture label. Never model a real product, logo or
trade dress, and keep the disclosure footnote a locked parameter in templates.

**Craft that matters.** Product photography lives on reflections: build a PMREM
environment from a dark room with tall emissive strip softboxes so glossy
cylinders get crisp vertical highlights. Make clear glass additive (it adds what
it reflects) so it never greys the backdrop, and put tinted contents inside.
Give the floor a soft contact shadow and a reflection that fades with depth.
One focal point; no clutter, no generic purple gradients.

**Performance.** Paint the backdrop once on a 2D canvas behind a transparent
WebGL canvas so only product pixels are shaded and multisampled each frame;
draw the reflection with a cheap custom shader; redraw the copy layer only
while it moves. Avoid per-frame 2D grain, bloom by default and shadow maps.
Target at most 8 s of render per output second at 1080x1920.

**Parameters.** `form` (enum), `name`, `tagline`, `cta`, `footnote` (strings
with `maxLength`), `palette` (ground, ink, accent), `body_color` and a named
`colorway`, `finish`, `move`, `lighting`, `spin`, `reflection`, `glow`, `grain`,
`msaa`. Ship at least four presets named by look, not by shape.

**Rules and checks.** Fit copy with `vg.fit` (throw when it cannot fit), choose
ink with `vg.readable`, derive every beat from the duration and document the
beat times for sound cues (a swell into the light sweep, an impact on the name,
a click on the call to action). Render every preset at 1080x1920 and 1920x1080,
look at contact sheets and full frames, and check the first frames are not blank.
