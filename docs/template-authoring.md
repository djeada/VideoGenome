# Authoring VideoGenome templates (v0.1)

Blueprints are source-controlled JSON under `templates/<category>/<slug>/blueprint.json`. Each blueprint is a **production recipe** rather than a generated video or a renderer program.

## Author workflow

1. Specify format, audience, viewer outcome and the narrative recipe in `title`, `description`, `category` and `tags`.
2. Define required **inputs** with types. Use references such as `input_refs: ["product_images"]` on shots; the input key must exist.
3. Set a coherent **style**, output geometry, frame rate, and candidate `engines`.
4. Write ordered scenes and shots. Choose the material kind that reflects reality: `footage`, `talking_head`, `screen_capture`, `generated_video`, `motion_graphics`, `still_image`, `3d`, `animation` or `composite`.
5. Allocate explicit frame counts; every scene's shot frame counts must sum to its `duration_frames`.
6. Capture constraints under `rules`, including elements the content-filling model may not change. In v0.1 these are advisory declarations, not a runtime policy enforcement system.
7. Specify `quality_gates` explicitly. Do not label perceptual or legal judgments as automatically enforced.
8. Run `python -m tools.validate` and `python -m unittest discover -s tests -v`; submit with expected output examples and reviewer notes.

## Reference categories

- `commercial/product-reveal`: premium hybrid with generated video and graphics.
- `social/ugc-testimonial`: authentic speaking footage, b-roll and platform-safe captions.
- `educational/software-explainer`: accurate screen recording with guided visual callouts.

Avoid claiming that arbitrary AI video models can render text or exact product marks reliably. For identities, product claims, filmed participants, music and stock media, provide human approval and rights evidence in the eventual asset manifest.

## Versioning policy

- `schema_version` changes when the blueprint contract changes. Current contract: `0.1.0`.
- `version` is the template's own semantic version, independent from `schema_version`.
- Breaking changes require a new major schema version and migration tooling. Keep template IDs stable across non-breaking edits.
- This first schema is intentionally small. Template inheritance, structured audio tracks, safe binding syntax, asset provenance, transitions, multilingual variants and machine-executable QA will be added in future versions.

## Acceptance checklist

- [ ] Reusable content slots and clear locked creative decisions
- [ ] Frame-accurate scene durations and unique shot IDs
- [ ] Complete declared references and portable execution hints
- [ ] Clear captions/audio requirements and platform format
- [ ] Legal/consent/product-accuracy concerns surfaced as review gates
- [ ] Example content and reproducible render evidence when rendering exists
