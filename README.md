# VideoGenome

**Encode creativity. Generate anything.**

VideoGenome is an open, **renderer-independent specification and repository** for reusable video-production expertise. More capable models can author and refine professional blueprints; smaller models can select them and supply structured content without reinventing directing, cinematography, pacing, sound, design, and production logic for every video.

The ambition spans **all video formats**: live-action commercials, UGC, explainers, documentaries, tutorials, 3D animation, AI-generated scenes, screen recordings, music videos and hybrids. It is not just a motion-graphics template collection.

## Status

**Early foundation, not a video renderer.** This repository currently includes a versioned blueprint JSON Schema, three reference blueprints, a CLI validator, tests and architecture notes. Rendering, media generation, asset management and automated aesthetic scoring are **planned**, not implemented.

## Try it

Requirements: Python 3.10+

```bash
python -m pip install -r requirements-dev.txt
python -m tools.validate
python -m unittest discover -s tests -v
```

Validate a specific file:

```bash
python -m tools.validate templates/commercial/product-reveal/blueprint.json
```

## How it works

1. A **template author** (a specialist or frontier model) encodes narrative structure, scene/shot recipes, artistic constraints, required inputs, engine hints and quality gates.
2. A **template filler** (often a smaller model) chooses a template and supplies brand-approved copy, source footage, product images, voice or other input values.
3. A future **planner** resolves assets, timing and capabilities; **adapters** hand shots to editing, code, 3D or generative-video engines.
4. A future **assembler** produces the timeline and a **QA pipeline** checks technical rules plus human-review gates.

The blueprint is the portable contract, **not executable code**. A renderer must never interpret free-form prompt text as trusted instructions or pretend that a media-generation prompt guarantees visual fidelity.

## Examples

- [Cinematic product commercial](templates/commercial/product-reveal/blueprint.json) — generated hero shots + motion graphics
- [UGC testimonial](templates/social/ugc-testimonial/blueprint.json) — consent-cleared real footage + captions
- [Software explainer](templates/educational/software-explainer/blueprint.json) — genuine screen capture + annotations

See [architecture](docs/architecture.md) and [authoring guide](docs/template-authoring.md).

## Principles

- **Engine-neutral core:** code renderers, NLEs, Blender, FFmpeg and generative providers are adapters, not the source of truth.
- **Reusable hierarchy:** archetype → narrative → scene → shot → production execution.
- **Bounded agency:** schemas and locked creative decisions constrain low-cost model customization.
- **Honest quality claims:** schema checks are implemented; perceptual, legal, authenticity and identity checks still require external systems or human review.
- **Reproducible provenance:** future manifests should record asset origins, rights, prompt/model versions, seeds when supported, costs and approvals.

Licensed under MIT. Contributions welcome once the contribution process is defined.
