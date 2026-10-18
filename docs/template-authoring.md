# Authoring VideoGenome templates

Blueprints are source-controlled JSON under `templates/<category>/<slug>/blueprint.json`. Each blueprint is a **production recipe** rather than a generated video or a renderer program.

## Author workflow

1. Specify format, audience, viewer outcome and the narrative recipe in `title`, `description`, `category` and `tags`.
2. Define required **inputs** with types. Use references such as `input_refs: ["product_images"]` on shots; the input key must exist.
3. Set a coherent **style**, output geometry, frame rate, and candidate `engines`.
4. Write ordered scenes and shots. Choose the material kind that reflects reality: `footage`, `talking_head`, `screen_capture`, `generated_video`, `motion_graphics`, `still_image`, `3d`, `animation` or `composite`.
5. Allocate explicit frame counts; every scene's shot frame counts must sum to its `duration_frames`.
6. Capture constraints under `rules`, including elements the content-filling model may not change. The job contract exposes only declared inputs and asset bindings; it does not permit style, scene or timeline overrides. Arbitrary custom policies in `rules.notes` still require review.
7. Specify `quality_gates` explicitly. Do not label perceptual or legal judgments as automatically enforced.
8. Mark how a writer model may fill each text input (`fill`: `write`, `verbatim` for names, quotes, testimonials and approved wording, `never` for what only a person supplies), and add one to three `copy_examples`: a realistic brief and the ideal values, with a note on why they work. They teach small models your intended tone and length, and the validator holds them to the same checks as a writer's reply. See [briefs and writers](briefs-and-writers.md).
9. Run `python -m tools.validate` and `python -m unittest discover -s tests -v`; submit with expected output examples and reviewer notes. Try the template end to end with `videogenome create TEMPLATE --brief ...` and add a few briefs for it to a bench suite.

## Reference categories

- `commercial/product-reveal`: premium hybrid with generated video and graphics.
- `social/ugc-testimonial`: authentic speaking footage, b-roll and platform-safe captions.
- `educational/software-explainer`: accurate screen recording with guided visual callouts.
- `educational/title-card-sequence`: executable typographic explainer demonstrating the 0.3.0 title-card system, dips and a blank-picture gate.
- `social/vertical-tips`: executable 9:16 listicle with platform-UI safe zones, numbered kickers, an optional music bed and -14 LUFS mastering gates.
- `educational/captioned-explainer`: executable still-and-title recipe with layered audio, fixed caption timing and checked copy limits; see [the editorial guide](editorial-timeline.md).
- `social/kinetic-promo`, `educational/steps-explainer`, `commercial/title-sting`: code-animated shots (`kind: animation`) produced by `scene.*` browser recipes, with sound cues locked to the scene's own beats. They show how to turn a one-off animation into a fillable template: the copy and colours are recipe parameters, and the template exposes only the slots and a few named looks.

Avoid claiming that arbitrary AI video models can render text or exact product marks reliably. For identities, product claims, filmed participants, music and stock media, provide human approval and rights evidence in the eventual asset manifest.

## Versioning policy

- `schema_version` changes when the blueprint contract changes. Supported contracts: `0.1.0` to `0.5.0`. The optional audio/caption `timeline` requires `0.2.0`; title-card typography, kickers, transitions, programme fades, loudness targets, poster frames and machine-checked gates require `0.3.0` ([reference](motion-design-and-delivery.md)). Old templates continue to work unchanged.
- `version` is the template's own semantic version, independent from `schema_version`.
- Breaking changes require a new major schema version and migration tooling. Keep template IDs stable across non-breaking edits.
- Structured audio tracks and caption cues are available in `0.2.0`; typography, transitions, mastering and technical gate checks in `0.3.0`. Safe text-slot binding and asset provenance are implemented by the compiler. Template inheritance, multilingual variants and machine-executable *aesthetic* QA remain planned.
- Schema `0.4.0` adds producible inputs (`inputs.<name>.produce` with a capability, request template, voice/style roles and references) and the `model_3d` input type; see [plugins and pipelines](plugins-and-pipelines.md). Name capabilities, never vendors.
- Schema `0.5.0` adds `inputs.<name>.fill` and `copy_examples` for brief filling; see [briefs and writers](briefs-and-writers.md).
- Studio or private templates can live outside this repository: point `--templates DIR` or `VIDEOGENOME_TEMPLATE_PATH` at a directory of `*/blueprint.json` files. Template ids must be unique across all trusted directories.

## Acceptance checklist

- [ ] Reusable content slots and clear locked creative decisions
- [ ] Frame-accurate scene durations and unique shot IDs
- [ ] Complete declared references and portable execution hints
- [ ] Clear captions/audio requirements and platform format
- [ ] Legal/consent/product-accuracy concerns surfaced as review gates
- [ ] Example content and reproducible render evidence when rendering exists
- [ ] Fill policies on every text input that must not be invented, and copy examples that pass validation
