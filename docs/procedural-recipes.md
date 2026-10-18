# Procedural recipes: code-generated visuals and audio that models tweak

A **recipe** is a small, deterministic program plus a manifest of typed,
documented parameters. Recipes produce real media: moving backgrounds, stills,
music beds and sound effects. They need no models, downloads or licences
(MIT), and the same spec renders the same bytes every time.

The point is a division of labour:

| Who | Does | Never does |
|---|---|---|
| Recipe author (human or frontier model) | Writes the code once, chooses good defaults, names presets, bounds every parameter | — |
| Template author | Picks the recipe and locks the art direction: preset, palette, speed | — |
| Content model | Picks from the choices a template exposes (e.g. `mood: reflective`), or edits params within their schema | Writes or edits code |
| Renderer | Runs the recipe in a subprocess with a validated spec | Executes job text |

~~~bash
videogenome recipes                       # catalog: id, media, runtime, presets, params
videogenome recipes --json                # full schemas for agents
videogenome recipe visual.aurora --preset sunrise --set speed=0.08 -o preview.mp4
videogenome recipe audio.ambient-pad --preset reflective --set key='"A"' --duration 20 -o bed.wav
~~~

`--set` values are parsed as JSON when possible. The command prints the fully
resolved params, so a model can iterate: render, inspect, adjust a number, render again.

## The catalog

| Recipe | Runtime | Media | Use |
|---|---|---|---|
| `visual.aurora` | Python/numpy | video, image | Flowing domain-warped gradient: calm premium backdrops |
| `visual.bokeh` | Python/numpy | video, image | Cinematic out-of-focus lights in depth layers |
| `visual.dot-wave` | Python/numpy | video, image | Perspective dot grid rippling with interfering waves |
| `visual.shader-gradient` | Browser (WebGL) | video, image | Four-colour mesh gradient fragment shader |
| `visual.flow-lines` | Browser (Canvas 2D) | video, image | Generative flow-field line art |
| `scene.kinetic-type` | Browser, clock | video, image | Kinetic typography reel: masked word rises, accent-circle full stop that swells into the next ground |
| `scene.steps` | Browser, clock | video, image | Process explainer: title, numbered nodes on a self-drawing connector, notes, check marks, recap |
| `scene.title-sting` | Browser, clock | video, image | Brand/title reveal: letters fly in from depth, impact ring and sparks, light sweep, tagline |
| `scene.stat-reveal` | Browser, clock | video, image | One to four statistics that roll up with labels, meters and a recap |
| `scene.chart-story` | Browser, clock | video, image | Bars, columns or a line that grow from zero, focus the key value and land a takeaway |
| `scene.feature-launch` | Browser, clock | video, image | Stylised app UI with camera moves, cursor clicks and three feature callouts |
| `scene.event-countdown` | Browser, clock | video, image | Event teaser: 3-2-1 or days-to-go countdown into a poster lockup |
| `scene.how-it-works` | Browser, clock | video, image | System diagram: nodes and self-drawing arrows with packets, captions and a lit finale |
| `scene.history-timeline` | Browser, clock | video, image | Camera travelling along a dated axis with pins, cards and a summary |
| `scene.quote-loop` | Browser, clock | video, image | A quote set phrase by phrase over silk, dust or gradient generative art |
| `scene.beat-visualizer` | Browser, clock | video, image | Rings, bars or orbit visuals locked to a tempo |
| `scene.route-map` | Browser, clock | video, image | A route drawn on Natural Earth coastlines with stops, counters and cards |
| `scene.code-snippet` | Browser, clock | video, image | Editor with syntax highlighting, typed code, a key line and terminal output |
| `scene.motion-showreel` | Browser, clock | video, image | Shape morphs, circular kinetic type, wipes and a name lockup |
| `scene.product-3d` | Browser, clock, three.js | video, image | Studio-lit stand-in product (bottle, can, jar, box, device) with camera move and copy |
| `scene.cinematic-3d` | Browser, clock, three.js | video, image | Generated valley flyover or orbital sunrise ending on a contrast-checked title |
| `audio.ambient-pad` | Python/scipy | audio | Voice-led pads, sub, bell sparkles, convolution reverb |
| `audio.lofi-beat` | Python/scipy | audio | Swung drums, FM electric piano 7ths, bass, vinyl, tape wow |
| `audio.pulse` | Python/scipy | audio | Four-on-the-floor tech bed with plucks and sidechain pump |
| `audio.transition` | Python/scipy | audio | Whoosh, riser, impact, swell, reverse cymbal, soft click |

Audio beds are mastered to **−20 LUFS** (BS.1770, verified against FFmpeg) with
headroom, so they sit under speech. The programme master then sets delivery
loudness, and timeline ducking lowers beds under narration.

## Using recipes in templates

Lock a recipe as a producible input (schema 0.4.0):

~~~json
"backdrop": {"type": "video", "required": false,
  "description": "Moving background behind every card",
  "produce": {"capability": "procedural", "request": {
    "recipe": "visual.bokeh", "preset": "minimal", "width": 540, "height": 960,
    "params": {"palette": ["#FF5A36", "#FFB199", "#F5F5F0"], "count": 26}}}}
~~~

and expose a safe choice to the content model:

~~~json
"energy": {"type": "string", "required": false, "enum": ["upbeat", "product", "calm-tech"],
           "default": "upbeat", "description": "Music energy"},
"music": {"type": "audio", "required": false, "description": "Music bed",
  "produce": {"capability": "procedural", "request": {"recipe": "audio.pulse", "preset": "{{energy}}"}}}
~~~

* `"{{slot}}"` as a whole value keeps the input's type (numbers stay numbers).
* Request `width`/`height` may be lower than the output size for soft
  backgrounds; the renderer cover-scales them. That cuts render time 2–4×.
* `style.title_card.background_input` puts a video or image behind every card.
  Its motion continues across cards, and `background_dim` darkens it in RGB for legibility.
* The validator checks that the recipe exists, the preset exists, and every
  param name is real. The recipe's JSON Schema validates values when the job is produced.
* Duration is automatic: a background spans the programme, a music bed spans
  its track, a transition sound spans its track window.

Profiles can also serve *plain* capabilities from recipes: the `procedural`
profile routes `music`, `video` and `image` to default recipes. A template's
`style` role (e.g. `"style": "reflective"`) then selects a matching preset.
So the same template can draw its music from a CC0 library, a recipe or a supplied file.

## Writing a recipe

~~~text
recipes/<area>/<name>/
  recipe.json        # manifest (schemas/recipe.schema.json)
  <name>.py          # runtime "python"  -> calls kit.run(render)
  index.html         # runtime "browser" -> vgSetup(spec) + vgRender(frame, t), or "timing": "clock"
~~~

`recipe.json` declares `id` (`area.name`), `version`, `media`, `runtime`,
`entry`, a `params` JSON Schema (every property needs `default` and
`description`; `additionalProperties: false`), named `presets`, `license`,
`tags` and a `cost` estimate. `catalog.discover()` rejects invalid defaults or presets.

**Python** recipes receive a `kit.Spec` (`params`, `media`, `width`, `height`,
`fps`, `duration_seconds`, `seed`, `sample_rate`, `output`):

~~~python
from videogenome.procedural import kit

def make_frame(spec: kit.Spec, index: int):
    ...                       # numpy H x W x 3 floats in [0, 1]

def render(spec: kit.Spec) -> None:
    with kit.VideoWriter(spec) as video:          # frame-exact H.264 or one PNG
        for frame in kit.frames_in_parallel(make_frame, spec):
            video.write(frame)

if __name__ == "__main__":
    kit.run(render)
~~~

Useful helpers:

| Module | Contents |
|---|---|
| `kit` | OKLab palette LUTs (`palette_lut`, `sample_lut`), `ValueNoise3` with `fbm`, `grid`, `vignette`, `film_grain`, dithered `to_uint8`, `write_wav` |
| `shapes` | Anti-aliased glowing discs in linear light, gradients, blur and upscale |
| `dsp` | Theory (`chord`, `voice_lead`, scales), band-limited `additive` oscillators, `adsr`, Butterworth filters with time-varying `sweep_lowpass`, convolution `reverb`, ping-pong `delay`, `pump`, `loudness_lufs`, `band_energy`, `master(target_lufs=...)` |
| `instruments` | Kick, snare, clap, hat, FM electric piano, pluck, bass, sub, pad, vinyl crackle, tape wow |

**Browser** recipes are self-contained HTML. The harness:
- sets the viewport to the output size;
- **blocks every network request** (no CDNs);
- seeds `Math.random` from `spec.seed`;
- calls `vgRender(frame, t)` with harness time (never the wall clock);
- captures each frame into FFmpeg.

Use WebGL with `preserveDrawingBuffer: true`, or Canvas 2D. Needs `pip install
videogenome[browser]` and `playwright install chromium-headless-shell`.

### Clock timing: ordinary animation code, rendered frame-exactly

`"timing": "clock"` lets a browser recipe animate the way people and frontier
models usually write motion graphics: `requestAnimationFrame` loops,
`performance.now()`, `Date`, `setTimeout`/`setInterval`, CSS animations and
transitions, the Web Animations API, and libraries built on them (GSAP,
anime.js, Three.js clocks). Before any page script runs, the harness replaces
every one of those clocks with a virtual clock. It then advances that clock by
exactly `1/fps` between screenshots: timers fire in due order, animation-frame
callbacks receive the virtual time, CSS and WAAPI animations are pinned to it,
and `Date` starts at 2026-01-01T00:00:00Z. The page reads its parameters from
`window.vgSpec` (`params`, `width`, `height`, `fps`, `duration_seconds`, `seed`).

The same page renders to the same bytes every time, at any resolution and
frame rate, with no dropped or duplicated frames. That is what makes a
model-written animation reusable: the code is written once, its copy and
colours become typed parameters, and a template exposes only safe choices.

Clock-timed pages must still be self-contained. Requests outside the page's
own directory are blocked, and audio produced in the page (Web Audio, `<audio>`)
is not captured: sound comes from audio recipes or supplied tracks in the
template's timeline, cued to the scene's beats.

### Scene recipes

`scene.*` recipes are whole shots, not backgrounds. They take on-screen copy
as string parameters with a `maxLength`, measure real glyphs to fit it, and
throw (so the render fails loudly) if text cannot fit rather than overflowing.
Copy is drawn with `fillText`, never parsed as HTML. `videogenome fill` reads
each text parameter's limit and description from the recipe schema, so a
writer model is told exactly how much room it has.

### Capturing any HTML animation

`videogenome capture` applies the same virtual clock to any self-contained
page, such as an animation a model just wrote:

~~~bash
videogenome capture scene.html -o scene.mp4 --size 1080x1920 --fps 30 --duration 12
videogenome capture scene.html -o still.png --size 1920x1080 --at 4.5
videogenome capture scene.html -o scene.mp4 --set 'title="Hello"'   # -> window.vgSpec.params
~~~

It verifies the frame count of the result. Use it to audition a page, then
promote the page to a recipe: move hard-coded copy, colours and timing into
`params` with bounds and defaults, add presets, and review contact sheets.

Rules every recipe follows:
1. **Deterministic:** all randomness comes from `spec.seed` (and, for frames, the
   frame index), so any frame can be rendered alone and parallel output equals serial output.
2. **Exact:** produce exactly `round(duration × fps)` frames or `duration × 48000` samples.
3. **Clean:** dither or grain against banding, anti-alias edges, envelope every
   note, keep peaks below −1 dBFS, no DC.
4. **Measured, not assumed:** check frames by eye (contact sheets) and audio with
   `dsp.loudness_lufs`, `dsp.band_energy` and spectrograms before shipping presets.
5. **Offline and original:** no network, no third-party samples, shaders or fonts
   inside the recipe; declare the licence.

Add your own recipe directories with `VIDEOGENOME_RECIPE_PATH`, or the
`recipe_dirs` config of a `procedural` provider in a pipeline profile.

## Honest limits

* The music is synthesised (additive, FM and noise models), not sampled
  instruments. It is clean and musical, but it won't pass for a studio recording.
* The arrangements loop their progressions with seeded variation; there are no
  composed intros, bridges or endings beyond fades.
* Python visuals cost about 2–4 s of compute per output second at 720p with
  parallel workers. Browser recipes depend on software WebGL in headless Chromium;
  scene recipes take about 3–4 s per output second at 1080×1920.
* The virtual clock covers the timing APIs listed above. A page that measures
  real elapsed time some other way (for example, a `Worker` with its own timers,
  or media element playback) is not frame-exact, and in-page audio is not captured.
* Recipe output is judged by measurements and contact sheets in CI. Whether it
  *looks and sounds good* is still a human gate.
