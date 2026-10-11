# VideoGenome

**Encode creativity. Generate anything.**

VideoGenome is an open framework for **model-independent, reusable video production intelligence**. Expert directors and frontier models can package their creative decisions into controlled, composable blueprints; smaller models supply the content, approved footage and assets required to execute them. The goal covers every kind of video, not just motion graphics: live action, social/UGC, commercials, explainers, documentaries, tutorials, generated video, animation, 3D and hybrids.

> **Status: experimental production kernel.** We now have a real input-to-timeline compiler and an FFmpeg reference renderer, **not** a universal video-generation engine or a fully featured nonlinear editor. See [supported vs planned capabilities](docs/production-pipeline.md).

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

## Design layers

| Layer | Responsibility | Status |
|---|---|---|
| Blueprint | Versioned creative intent, style, timings, shots and quality declarations | v0.1 available |
| Job | Typed content slots, licensed assets, explicit per-shot source bindings | v0.1 available |
| Compiler | Schema + semantic validation, rights attestations, path controls, deterministic ordered shot IR | Available |
| Media adapter | Standardized graphics, stills and pre-rendered video clips, preserves embedded speech audio | FFmpeg reference available |
| QA and provenance | File checksums, duration/resolution verification, unevaluated-gate receipt | Partial |
| Provider adapters | LLM planning, footage retrieval, generation, 3D, NLE, character continuity | Planned |
| Advanced timeline | Multi-track compositing, transitions, beat sync, caption engine, mixing | Planned |
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
