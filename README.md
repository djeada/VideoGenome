# VideoGenome

**Encode creativity. Generate anything.**

VideoGenome is an open framework for **model-independent, reusable video production intelligence**. Expert directors and frontier models can package their creative decisions into controlled, composable blueprints; smaller models supply the content, approved footage and assets required to execute them. The goal covers every kind of video, not just motion graphics: live action, social/UGC, commercials, explainers, documentaries, tutorials, generated video, animation, 3D and hybrids.

> **Status: experimental production kernel with audio/caption post-production.** The compiler and FFmpeg adapter assemble video, layer timed audio and burn in captions. Video generation and a fully featured nonlinear editor remain planned. See [supported vs planned capabilities](docs/production-pipeline.md).

## Discover templates and prepare small-model jobs

The catalog is machine-readable and can be searched without generating code:

~~~bash
python -m videogenome catalog --category social
python -m videogenome catalog --orientation landscape --shot-kind motion_graphics
python -m videogenome inspect commercial.cinematic-product-reveal
python -m videogenome scaffold educational.title-card-sequence -o /tmp/my-job.json
~~~

A scaffold is **intentionally incomplete**: media inputs and rights records must be supplied by an authorized user or asset pipeline, and no quality gate is automatically approved. The catalog describes template expectations, not proof that any media provider can generate every shot.

## Working vertical slice

Python 3.10+, FFmpeg and ffprobe installed, and a local font-enabled FFmpeg build:

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

The three-card example requires **no external footage or API keys**. It produces a 9-second 1280×720 MP4. Integration tests also generate and assemble actual video (with sound), still images and graphics. A production job using generated footage must supply an already-rendered, approved media asset; the system does not call generative-video models yet.

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
| Blueprint | Versioned creative intent, style, timings, shots and quality declarations | v0.1 supported; v0.2 adds editorial timeline |
| Job | Typed content slots, licensed assets, explicit per-shot source bindings | v0.1 available |
| Compiler | Schema + semantic validation, rights attestations, path controls, deterministic ordered shot IR | Available |
| Media adapter | Graphics, stills, pre-rendered clips, layered audio and timed captions | FFmpeg reference available |
| QA and provenance | Source/output hashes, frame count, duration/resolution checks, executed timeline, unevaluated-gate receipt | Partial |
| Provider adapters | LLM planning, footage retrieval, generation, 3D, NLE, character continuity | Planned |
| Audio/caption timeline | Overlapping audio, source trim, gain/fades, source sound policy, burned-in captions | Available in v0.2 blueprints |
| Advanced picture timeline | Multi-track picture compositing, transitions and beat sync | Planned |
| Perceptual evaluation | Visual identity, storytelling quality, subjective design, continuity | Planned |

**Important:** Rights are self-attested by the job submitter. Human quality gates remain *not evaluated* unless explicitly approved, and declared automated gates are **not automatically executed** just because they are named. Do not treat a successful FFmpeg render as publication approval.

## The key abstraction

A video is described along independent axes—**intent, narrative, visual grammar, production method and delivery**. A documentary can contain cinematic footage and motion graphics; a social ad can combine filmed testimony, generated b-roll, animation and software screen recording. Those are components and capabilities, not mutually exclusive genres.

The **frontier model** contributes the blueprint; the **smaller model** is restricted to its named input slots and approved assets. The reference compiler rejects undeclared inputs and unauthorized top-level overrides. Style and locked sequencing live only in the versioned template.

Explore:

- [Video ontology and capabilities](docs/video-ontology.md)
- [Production pipeline and concrete contract](docs/production-pipeline.md)
- [Security, trust and media rights](docs/security-and-rights.md)
- [Milestone-based roadmap and acceptance criteria](docs/roadmap.md)
- [Blueprint authoring](docs/template-authoring.md)
- [Cinematic product commercial](templates/commercial/product-reveal/blueprint.json)
- [UGC testimonial](templates/social/ugc-testimonial/blueprint.json)
- [Screen-capture explainer](templates/educational/software-explainer/blueprint.json)
- [Executable hybrid reference](templates/reference/hybrid-assembly-smoke/blueprint.json)

MIT licensed. New template contributions should include input contracts, examples, provenance, validation tests and (when renderable) representative output evidence.
