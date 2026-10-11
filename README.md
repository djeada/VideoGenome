# VideoGenome

**Encode creativity. Generate anything.**

VideoGenome is an open framework for **model-independent, reusable video production intelligence**. Expert directors and frontier models can package their creative decisions into controlled, composable blueprints; smaller models supply the content, approved footage and assets required to execute them. The goal covers every kind of video, not just motion graphics: live action, social/UGC, commercials, explainers, documentaries, tutorials, generated video, animation, 3D and hybrids.

> **Status: v0.4, a composable production tool.** Pick a template, fill the text, and let *your* pipeline produce
> the rest: any TTS, image, video, music, typing or 3D tool plugs in through a general provider interface. That
> covers CLI tools, OpenAI-compatible servers, ComfyUI workflows, MCP servers and Python entry points. The
> FFmpeg renderer then assembles designed cards, transitions, mix, captions and loudness, with measured QA gates
> and a provenance receipt. See [plugins and pipelines](docs/plugins-and-pipelines.md) and the
> [open-source stack](docs/open-source-stack.md).

## Install

Requires Python 3.10+, and FFmpeg 6.1+ with ffprobe and fontconfig. Install [Inter](https://rsms.me/inter/) for on-brand typography
(`apt install fonts-inter`). Without it, the receipt records which font was used instead.

~~~bash
pip install .            # or: pip install -e .  (for development)
videogenome doctor       # checks FFmpeg, required filters, encoders and template fonts
~~~

## Make a video in four commands

~~~bash
videogenome catalog --self-contained --table           # templates that need only text
videogenome scaffold social.vertical-tips -o job.json   # skeleton with the required slots
$EDITOR job.json                                        # fill hook, tip_1..3, cta
videogenome render job.json -o out/tips.mp4 --receipt out/receipt.json
~~~

`render` writes these files:

| File | Contents |
|---|---|
| `tips.mp4` | H.264/AAC, frame count, resolution and duration verified |
| `tips.poster.jpg`, `tips.contact.jpg` | Poster frame and one tile per shot, for review |
| `tips.srt`, `tips.vtt` | Caption sidecars (when the template has captions) |
| `receipt.json` | Source/output hashes, pinned font, measured layout, loudness, gate results and caveats |

The command prints the measured loudness and each gate's status. It exits **3**
if an automated gate fails (the output is kept), and **1** if the job is
invalid. A job names its template by catalog id, so it works from any
directory. Studios can keep their own reviewed templates outside this
repository with `--templates DIR` or `VIDEOGENOME_TEMPLATE_PATH`.

| Template | Format | Needs |
|---|---|---|
| `educational.title-card-sequence` | 16:9, 9 s | Text only |
| `educational.narrated-slides` | 16:9, 22 s, captions, -16 LUFS | Text; images, narration and music are producible |
| `educational.code-typing-reel` | 9:16, 16 s | Text and code; typing clip is producible |
| `commercial.product-turntable` | 1:1, 9 s | Text and a `.glb` model; the turntable is producible |
| `educational.cc0-documentary` | 16:9, 21.5 s, captions | Text and topics; footage (CC0), narration and music are producible |
| `social.vertical-tips` | 9:16, 13.5 s, -14 LUFS | Text, optional music bed |
| `educational.captioned-explainer` | 16:9, 8 s, captions | Image, music, narration |
| `reference.hybrid-assembly-smoke` | 1:1, 3 s | Video clip, image |
| `commercial.cinematic-product-reveal`, `social.ugc-testimonial`, `educational.software-explainer` | Blueprints | Pre-produced footage (see each template) |

## Procedural visuals and audio that models tweak

Backgrounds, music beds and sound effects are **code-generated recipes**: Python/numpy or JS/WebGL
programs with typed, bounded parameters and named presets. They are deterministic, need no models,
and are MIT, so there are no rights questions. Template authors lock the art direction; content
models choose among the safe options a template exposes, or tweak parameters within their schema.
Nobody edits code at job time.

~~~bash
videogenome recipes                                   # 9 recipes: aurora, bokeh, dot-wave, shader, flow-lines, pads, lo-fi, pulse, SFX
videogenome recipe visual.flow-lines --preset ink -o preview.mp4
videogenome recipe audio.lofi-beat --preset focus --set bpm=78 --duration 20 -o bed.wav
videogenome make examples/vertical-tips/job.json --pipeline procedural -o out/tips.mp4
~~~

See [procedural recipes](docs/procedural-recipes.md) for the format and authoring rules.

## Compose your own pipeline

A blueprint says *what* is needed: "this narration can be produced by the `speech` capability from
`{{script}}` with the *narrator* voice". A pipeline profile, owned by you and never by the job, says *who*
produces it:

~~~bash
videogenome pipelines                     # animatic, open-source-local, blender-mcp, kokoro-fastapi, comfyui, ...
videogenome plugins                       # provider/renderer/analyzer/exporter types and capabilities
videogenome make examples/narrated-slides/job.json --pipeline animatic -o out/slides.mp4
videogenome make examples/code-typing-reel/job.json --pipeline open-source-local -o out/reel.mp4
~~~

| Capability | Verified open-source route | Also plugs in |
|---|---|---|
| `speech` | Kokoro-82M or Piper (`command`) | Kokoro-FastAPI, LocalAI (`openai-compatible`), espeak-ng, Qwen3-TTS → Chatterbox chains |
| `video`, `image`, `sound` | CC0 / public-domain search: Wikimedia Commons, Openverse (`cc0-stock`) | ComfyUI (Wan, LTX-Video, FLUX…), stable-diffusion.cpp |
| `music`, backgrounds, SFX | Procedural recipes (`procedural`) | Stable Audio / ACE-Step via ComfyUI, your own library |
| `typing` | [Type-Simulator](https://github.com/djeada/Type-Simulator) reels (`command`) | VHS, asciinema |
| `render_3d` | Blender `turntable.py` (`command`) or [blender-mcp-server](https://github.com/djeada/blender-mcp-server) (`mcp`) | ParaView MCP, any MCP server |

Routes can be a single provider, a `fallback` list or a `chain` (for example expressive TTS → voice
conversion). The `animatic` profile renders *any* template with labelled placeholders, so you can review
timing and layout before running a model. A supplied recording or footage always wins over generation;
every generated asset records provider, model, request hash and the operator's rights attestation.
Third-party packages add providers, renderers, analyzers or exporters through Python entry points.

## Discover templates and prepare small-model jobs

The catalog is machine-readable and can be searched without generating code:

~~~bash
videogenome catalog --category social
videogenome catalog --orientation landscape --shot-kind motion_graphics
videogenome inspect commercial.cinematic-product-reveal
videogenome scaffold educational.title-card-sequence -o /tmp/my-job.json
~~~

A scaffold is **intentionally incomplete**: media inputs and rights records must be supplied by an authorized user or asset pipeline, and no quality gate is automatically approved. The catalog describes template expectations, not proof that any media provider can generate every shot. `python -m videogenome` works identically from a source checkout.

## Development

~~~bash
python -m pip install -r requirements-dev.txt
python -m tools.validate
python -m unittest discover -s tests -v

# Compile a locked blueprint + small-model content to ordered shot IR
python -m videogenome compile examples/three-card-explainer/job.json -o /tmp/plan.json

# Render a real H.264/AAC MP4 and a QA/provenance receipt
python -m videogenome render examples/three-card-explainer/job.json \
  -o /tmp/videogenome.mp4 --receipt /tmp/videogenome-receipt.json
~~~

The three-card and vertical-tips examples require **no external footage or API keys**. Integration tests also generate and assemble actual video (with sound), still images, graphics, crossfades and a loudness-mastered music bed. A production job using generated footage must supply an already-rendered, approved media asset; the system does not call generative-video models yet.

## Design, transitions, mastering and QA

Schema 0.3.0 adds a locked [title-card typography system](docs/motion-design-and-delivery.md#title-cards) with measured copy fitting. It also adds
[crossfades and dips](docs/motion-design-and-delivery.md#transitions-and-programme-fades) that preserve frame timing,
[two-pass loudness mastering](docs/motion-design-and-delivery.md#loudness-mastering) and
[machine-checked quality gates](docs/motion-design-and-delivery.md#executed-measurements-and-machine-checked-gates).
Gates without a declared machine check stay `not_evaluated`; nothing aesthetic is claimed as measured.

## Layer audio and captions

The new [captioned explainer](templates/educational/captioned-explainer/blueprint.json) demonstrates a locked music bed, a second audio track, frame-timed captions and a picture cut:

~~~bash
python -m tools.create_editorial_demo -o /tmp/vg-editorial
python -m videogenome render /tmp/vg-editorial/job.json \
  -o /tmp/vg-editorial/demo.mp4 --receipt /tmp/vg-editorial/receipt.json
~~~

This reproducible example uses an original illustration and calibration tones, not human speech or finished music. Supply cleared recordings to the same typed audio slots for real work. Audio tracks support trim, start time, gain and fades; captions enforce locked line and reading-speed limits. Existing v0.1 templates remain supported. See the [editorial timeline contract](docs/editorial-timeline.md) for a second brief, source-audio policies, versioning and limitations. CI uploads both rendered briefs for review.

## Design layers

| Layer | Responsibility | Status |
|---|---|---|
| Blueprint | Versioned creative intent, style, timings, shots and quality declarations | v0.1–v0.3 supported |
| Job | Typed content slots, licensed assets, explicit per-shot source bindings; template by catalog id | Available |
| Compiler | Schema + semantic validation, rights attestations, path controls, copy fitting, deterministic shot IR | Available |
| Media adapter | Designed title cards, stills, pre-rendered clips, transitions, layered audio, timed captions, loudness | FFmpeg reference available |
| QA and provenance | Hashes, frame/duration/resolution checks, pinned fonts, measured layout, loudness/blank/silence metrics, machine-checked gates | Available for technical checks |
| Delivery | MP4, SRT/WebVTT sidecars, poster, contact sheet | Available |
| Packaging | `pip install`, `videogenome` CLI, bundled templates, external template directories, `doctor` | Available |
| Plugins | Providers (command, OpenAI-compatible, ComfyUI, MCP, placeholder, entry points), renderers, analyzers, exporters, pipeline profiles | Available |
| Production | Producible inputs, routes with fallback and chains, caching, timing conformance, provenance | Available |
| Take selection and re-timing | N takes judged by analyzers (WER, speaker similarity); audio-driven timing | Planned |
| Advanced picture timeline | Multi-track compositing, wipes/pushes, reframing to multiple aspect ratios, beat sync | Planned |
| Perceptual evaluation | Visual identity, storytelling quality, subjective design, continuity | Planned |

**Important:** Rights are self-attested by the job submitter. Human quality gates remain *not evaluated* unless explicitly approved, and automated gates execute **only** when they declare a supported machine `check`; naming a gate does not run it. Do not treat a successful FFmpeg render as publication approval.

## The key abstraction

A video is described along independent axes—**intent, narrative, visual grammar, production method and delivery**. A documentary can contain cinematic footage and motion graphics; a social ad can combine filmed testimony, generated b-roll, animation and software screen recording. Those are components and capabilities, not mutually exclusive genres.

The **frontier model** contributes the blueprint; the **smaller model** is restricted to its named input slots and approved assets. The reference compiler rejects undeclared inputs and unauthorized top-level overrides. Style and locked sequencing live only in the versioned template.

Explore:

- [Video ontology and capabilities](docs/video-ontology.md)
- [Production pipeline and concrete contract](docs/production-pipeline.md)
- [Security, trust and media rights](docs/security-and-rights.md)
- [Milestone-based roadmap and acceptance criteria](docs/roadmap.md)
- [Blueprint authoring](docs/template-authoring.md)
- [Motion design, transitions, mastering and QA](docs/motion-design-and-delivery.md)
- [Plugins and pipelines](docs/plugins-and-pipelines.md)
- [Procedural recipes](docs/procedural-recipes.md)
- [Open-source stack](docs/open-source-stack.md)
- [Changelog](CHANGELOG.md)
- [Cinematic product commercial](templates/commercial/product-reveal/blueprint.json)
- [UGC testimonial](templates/social/ugc-testimonial/blueprint.json)
- [Screen-capture explainer](templates/educational/software-explainer/blueprint.json)
- [Executable hybrid reference](templates/reference/hybrid-assembly-smoke/blueprint.json)

MIT licensed. New template contributions should include input contracts, examples, provenance, validation tests and (when renderable) representative output evidence.
