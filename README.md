# VideoGenome

**Encode creativity. Generate anything.**

Frontier models can write striking videos as code: kinetic type, data stories,
product launches, explainers, 3D scenes. Galleries such as
[awesome-opus5-5-videos](https://github.com/yihui-dev/awesome-opus5-5-videos)
collect hundreds of them, each a one-off prompt and a screen recording.
VideoGenome is the system behind that kind of result. A class of video is
written once as deterministic, parameterised code, locked into a template with
its timing, sound and quality gates, and then produced from a plain-language
brief by anyone: a person in a web UI, an agent over MCP, a script, or a small
local model.

~~~bash
videogenome create social.kinetic-promo --pipeline procedural-writer -o out/harbourline.mp4 \
  --brief "Promo for Harbourline, a ferry app: buy tickets in ten seconds, see live departures, board by scanning your phone."
~~~

The output is a frame-exact MP4 with measured loudness and gates, a provenance
receipt and a review page. Names, quotes and numbers are copied from the brief,
never invented. Add `--format all` and the same job is also laid out and
rendered for 16:9 and 1:1 ([delivery formats](docs/delivery-formats.md)).

## The library: prompt, code or ready to fill

Every class of video is a **genome** with a level derived from what actually
exists, so it is always clear what you are getting:

| Level | What exists | What you do |
|---|---|---|
| **TEMPLATE** | Code plus a locked template with typed slots, copy examples and gates | Give a brief or fill the slots, get a finished video |
| **CODE** | A recipe: deterministic code with bounded parameters and presets | Pick a preset, tune parameters, preview |
| **PROMPT** | An authoring prompt only | Hand it to your agent, which writes the code; preview with `capture`; promote it |

~~~bash
videogenome library            # every class by level
videogenome genome route-map   # one class: templates, recipes, what you bring, limits
videogenome genome physics-sim --prompt   # the authoring prompt for an agent
~~~

| Family | Ready to fill (template level) |
|---|---|
| Typography | Kinetic type promo · title-card explainer |
| Data | Headline stat reveal · animated chart with one takeaway |
| Explainer | How-it-works system diagram · history timeline · step-by-step · narrated slides · captioned still · software walkthrough (your recording) |
| Brand | Title sting · motion-design showreel |
| Product | 3D product hero (three.js stand-in: bottle, can, jar, box, device) · app launch with stylised UI · product turntable (your .glb) · cinematic reveal (your footage) |
| 3D | Cinematic title over a generated valley flyover or orbital sunrise |
| Social | Event teaser (3-2-1 and days-to-go) · vertical tips listicle · UGC testimonial (your footage) |
| Story / maps | Route map on Natural Earth coastlines |
| Generative / music | Quote or lyric loop over generative art · tempo-locked beat visualizer |
| Code | Browser code reveal with syntax highlighting · typing reel (Type-Simulator) |

Every code-animated template above renders 16:9, 9:16 and 1:1 from one job
(the chart story: 16:9 and 9:16), each format reviewed frame by frame.
| Documentary | Mini documentary from CC0 footage |

Ready code: generative backdrops (aurora, bokeh, dot wave, mesh-gradient shader,
flow lines) and procedural music and sound (pads, lo-fi, pulse, transitions).
Prompt only, for now: physics simulations, character micro-stories, games in
attract mode, infinite zooms.

## Four ways in

| Who | Cockpit | Start |
|---|---|---|
| Anyone | **Studio**: a local web UI to browse the library, fill a template from a brief or a form with live checks, render, tune recipes, run your own HTML | `videogenome studio --pipeline procedural-writer --open` |
| Agents | **MCP server**: the agent reads slot contracts, writes the copy, checks it, renders and sees a contact sheet; it can also render HTML it wrote | `claude mcp add videogenome -- videogenome mcp --pipeline procedural --workspace ~/vg-runs` |
| Power users | **CLI** | `videogenome --help` |
| Your own code | **Capture**: any self-contained HTML animation renders unmodified and frame-exactly, with its Web Audio | `videogenome capture page.html -o page.mp4 --size 1080x1920 --duration 12` |

All four share one service layer, so they apply the same checks, pipelines,
gates and receipts. See [cockpits](docs/cockpits.md).

## Install

Requires Python 3.10+, FFmpeg 6.1+ with ffprobe and fontconfig, and the Inter
font for on-brand type (`apt install fonts-inter`).

~~~bash
pip install '.[procedural,browser]'         # core, Python recipes, browser scenes
playwright install chromium-headless-shell  # once: scenes, capture, Studio previews
videogenome doctor
ollama pull qwen2.5:3b                      # optional: the local writer in `procedural-writer`
~~~

## How a video is made

1. **Recipe (code).** A scene is an HTML page that animates with ordinary code
   (`requestAnimationFrame`, timers, CSS animations, three.js). A virtual clock
   advances it exactly one frame per screenshot, so the same parameters give the
   same bytes at any size. Copy is a bounded parameter, fitted with measured
   glyphs; a page throws rather than overflow.
2. **Blueprint (template).** It locks the recipe's look, the shot timing, sound
   cues on the scene's beats, loudness targets and gates, and opens typed slots.
   Each slot says what it is used for and how much it can hold. Facts are
   `verbatim` and must appear in the brief; numbers must sit next to their labels.
3. **Copy.** A writer model (`fill`, `create`), an agent (MCP), a person (Studio)
   or a script fills the slots. Every value is checked by the compiler, the
   renderer's glyph measurement, the narration budget and a layout pass that
   loads each scene with the copy in every delivery format. A brief that lacks a
   required fact ends `incomplete` (exit 4), with nothing invented.
4. **Pipeline.** The operator's profile decides which tools produce media:
   procedural recipes, CC0 search, TTS, Blender, ComfyUI, MCP servers, your own
   commands. Jobs and agents never choose providers.
5. **Render and review.** FFmpeg assembles, masters loudness and measures; the
   receipt records hashes, provenance and gate results, and the review page lists
   what still needs a human decision.

## Measured, not assumed

* `videogenome bench SUITE.json` runs a suite of briefs for a writer and
  reports fill rate, first-attempt rate and honest-refusal rate.
  `examples/briefs/` holds suites for every class. Each suite includes briefs
  that lack required facts.
* On 2026-10-18 a local Qwen2.5-3B met expectations on 52 of 59 briefs across
  12 suites, including 12 of 12 general briefs and every brief in the chart,
  timeline, quote, beat and showreel suites. The misses are listed in
  [briefs and writers](docs/briefs-and-writers.md). Slots a writer composes
  (code, system diagrams) can still be invented, and a stated number can be
  reused for the wrong slot, which is why templates keep human review gates.
* Automated gates measure loudness, true peak, blank picture and silence. Every
  aesthetic and factual judgement stays `not_evaluated` until a person approves
  it. Rights are self-attested. A successful render is not publication approval.

## Status and limits

**v0.7.0.**

* Templates driven by text and code render end to end with no API keys.
* Media-heavy templates render when you supply media or choose a pipeline that
  produces it.
* Scene renders use software WebGL in headless Chromium, at roughly 2–6 s of
  compute per output second at 1080×1920.
* Web Audio inside captured pages is recorded; `<audio>`/`<video>` element
  playback and Workers' own timers are not.
* Several pipeline profiles are verified only against fake servers;
  `videogenome pipelines` says which.

## Develop

~~~bash
python -m pip install -r requirements-dev.txt && python -m playwright install chromium-headless-shell
python -m tools.validate                      # blueprints, copy examples, recipes, genomes
python -m unittest discover -s tests -v
videogenome recipe-new scene.my-scene -o recipes/scene/my-scene [--three]
~~~

CI validates everything, renders the reference examples, and renders every
code-animated sample job for visual review.

## Documentation

- [Cockpits: Studio, MCP, CLI, capture](docs/cockpits.md)
- [Authoring a video class (genome, recipe, template)](docs/scene-authoring.md)
- [Briefs and writers](docs/briefs-and-writers.md)
- [Procedural recipes, scenes and capture](docs/procedural-recipes.md)
- [Blueprint authoring](docs/template-authoring.md) · [Video ontology](docs/video-ontology.md) · [Production pipeline](docs/production-pipeline.md)
- [Motion design, transitions, mastering and QA](docs/motion-design-and-delivery.md) · [Editorial timeline](docs/editorial-timeline.md)
- [Plugins and pipelines](docs/plugins-and-pipelines.md) · [Open-source stack](docs/open-source-stack.md)
- [Security, trust and media rights](docs/security-and-rights.md) · [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md) · [Changelog](CHANGELOG.md) · Agent roles: [AGENTS.md](AGENTS.md)

## Contributing and license

MIT licensed (three.js is vendored under its MIT licence; map data is Natural
Earth, public domain). See [CONTRIBUTING.md](CONTRIBUTING.md) and
[scene authoring](docs/scene-authoring.md). New classes need a genome with an
authoring prompt, recipes with presets, a template with fill policies and copy
examples, a sample job, bench briefs, and reviewed renders.
