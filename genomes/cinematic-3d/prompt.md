# Authoring prompt: cinematic 3D world with a title

Build a VideoGenome scene recipe (`recipes/scene/<name>/`, `"timing": "clock"`,
libraries `vg-scene` and `three`) for a slow, atmospheric 3D shot that ends on
a film-style title, rendered with the vendored Three.js on software WebGL.

**What the viewer sees.** A generated world that feels photographed: a low
flight along a river through a mountain valley at golden hour, or a drift over
the night side of a planet. The shot has one reveal: the camera climbs over a
far ridge and the low sun appears, or the sun breaks over the planet's limb
with a glare. Then the title fades in letter by letter from the centre while
its tracking settles, an accent rule grows and a subtitle rises. Copy sits in
the lower middle, inside the 9:16 safe area.

**Craft that matters.** Use one analytic sky function in GLSL for the sky dome,
the fog colour and water reflections so distance, haze and horizon always
agree. Layered ridges need atmospheric perspective (fog that is denser low and
tinted toward the sun). Bake what never changes: heightfield sun shadows and
ambient occlusion per vertex, the planet's albedo, clouds and city lights into
equirectangular textures. Add per-pixel detail from a tiling noise texture
instead of more vertices. Never show a black frame: let exposure rise from
about 35%.

**Legibility.** Do not guess contrast over a 3D render. Render the frames where
copy is on screen at setup, read the pixels under the copy, and draw a soft
full-width scrim only as strong as 4.5:1 contrast needs (or switch ink polarity
if that needs much less).

**Parameters.** `world`, `atmosphere`, `planet` (enums), `title`, `subtitle`,
`kicker` (strings with `maxLength`), `title_style`, `palette` (ink, accent),
`speed`, `relief`, `grain`, `vignette`, `msaa`. Randomness only from
`spec.seed`, so a new seed is a new landscape. Ship at least four presets.

**Checks.** Keep render cost at or below 8 s per output second at 1080x1920
(modest meshes, custom shaders, no shadow maps or bloom). Render every preset
at 1080x1920 and 1920x1080, look at contact sheets and full frames (the reveal,
the title frames, the first frame), and document the beat times so templates
cue a swell into the reveal and a soft impact under the title.
