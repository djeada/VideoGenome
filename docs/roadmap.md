# Milestone-based implementation roadmap

Goal: a stronger model contributes vetted filmmaking expertise once, and a less capable model can produce credible, consistent videos by filling approved slots. That is a **hypothesis to test**, not a quality guarantee.

## Stage 0 — executable kernel (this PR)

Deliver strict job contract, versioned templates, asset binding, frame compiler, source hashes and rights attestations, FFmpeg sequential render and truthful QA/provenance receipt. Include a completely self-contained title-card video and an automated hybrid fixture testing actual footage with recorded audio, still image and graphics.

Acceptance: no extra model/API keys; command-line render produces readable MP4; invalid inputs and traversal are rejected; CI covers compilation and integrated media output.

## Stage 1 — real editorial post-production

First implemented slice: [audio and caption timeline](editorial-timeline.md).
Schema v0.2 supports overlapping audio with trim/gain/fades, source sound
preservation or muting, and frame-timed captions with checked copy limits.
Two reproducible briefs run through one reusable template; decoded-media tests
verify the audio and caption behavior. Schema v0.3 adds measured title-card
typography, crossfades and dips, two-pass loudness mastering, executed
loudness/true-peak/blank/silence gates, SRT/WebVTT sidecars and an installable
CLI with a renderable 9:16 template. This does not complete the broader
Stage 1 acceptance criteria below.

Produce three finished, reviewable reference videos from permitted sources: (a) creator/testimonial social ad, (b) genuine software walkthrough, (c) premium product reveal. Implement multiple picture/audio tracks, transitions, captions, typography layout, audio mix policies, safe zones and aspect crops.

Acceptance: all three execute the *same* blueprint/job/IR contract; dialogue remains intelligible; subtitles meet reading/safe-zone rules; each exports 16:9 and/or 9:16 with reviewable crops; technical QA includes audio loudness, media integrity and visually compared golden frames.

## Stage 2 — producer and provider adapters

Add a capability registry and at least two distinct provider types, such as Blender-based 3D rendering and an AI video generator. Each adapter estimates cost, declares hard limitations, processes asynchronously, supports cancellation/timeouts, and records request/reference/version hashes. Cache accepted assets and allow shot-local retries.

Acceptance: constraints prevent incompatible or over-budget calls *before* generation; accepted outputs carry provenance; a failed generation can be replaced without rebuilding unrelated shots; missing identity precision triggers explicit fallback or review.

## Stage 3 — reusable expertise packages

Build independently versioned story/scene/shot/style/audio/evaluator recipes, typed composition and dependency locks, discovery search, previews, brand inheritance, editable-slot policy and review workflows. Introduce continuity ledgers for characters, products, spaces and time.

Acceptance: a new expert-authored package can be discovered, filled by a smaller model, validated and rendered without changing renderer code; identical brands and product marks remain consistent in an evaluation set; creative revisions produce diffable evidence.

## Stage 4 — production and distribution platform

Add robust multilayer compositing, advanced audio, localization, accessibility and cross-format delivery, NLE interchange, signed publication approvals, performance measurement and production cost analytics. Harden worker isolation, third-party rights and private assets for multi-tenant deployment.

Acceptance: complex mixed-media examples produce multiple platform versions, every mandatory gate is associated with verification evidence, and release history is auditable.

## Benchmark the underlying thesis

Create a rights-cleared, held-out set with diverse briefs: social testimonial, product commercial, interface tutorial, documentary interview, animated narrative and 3D visualization. Measure three conditions:

1. Frontier model writes bespoke video code for each brief.
2. Small model writes bespoke code for each brief.
3. Small model fills approved VideoGenome templates.

Use blinded human review and machine measurements for creative quality, narrative completeness, technical validity, accuracy, identity consistency, captions and brand. Compare **cost per accepted video**, revision counts and latency, not just raw generation speed. Publish failures and tradeoffs alongside wins.

## Contribution standards

A professional recipe contribution should include: its audience and outcome, allowed slots and locks, creative references, provider capabilities, all dependencies, rights declarations, a working sample job, a reference render or reproducible fixture, machine tests and a reviewer rubric. Quality claims without example outputs should not enter the trusted catalog.

v0.4 delivers the plugin layer of Stage 2: capabilities, provider/renderer/
analyzer/exporter interfaces with entry points, pipeline profiles with
fallback and chain routes, generic command/HTTP/ComfyUI/MCP adapters, cached
production with provenance, and verified local routes (Piper, Type-Simulator,
Blender, blender-mcp-server). Still missing from Stage 2: cost estimates,
asynchronous jobs with cancellation, and budget limits before generation.

Next:
- **Takes and judges**: generate N takes and select by analyzer scores (WER via
  faster-whisper, speaker similarity via ECAPA), as proven in the drama TTS work.
- **Audio-driven timing**: templates whose slots stretch to the produced
  narration instead of rejecting long expressive takes.
- **Producers of `model_3d`** (text/image-to-3D) feeding render_3d chains.
- Multi-aspect reframing and automatic ducking under dialogue.
