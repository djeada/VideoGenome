# Production pipeline and intermediate representation

## Working reference pipeline (current PR)

~~~
Expert-authored and reviewed blueprint
                +
Small-model job manifest (typed inputs, approved local media)
                |
        contract / semantic compiler
        - template and version resolution
        - input types, shot bindings, rights attestations
        - local media confinement and hashes
        - declared text slot substitution
                |
           planned shot IR
        - sequential absolute frame coordinates
        - source media refs + trim and fit
        - declared quality gates with honest status
                |
            FFmpeg adapter
        - generates graphics cards
        - holds still images
        - trims and scales pre-rendered footage
        - preserves existing dialogue when available
        - normalizes H.264/AAC
        - joins clips and probes output
                |
      MP4 + provenance/QA receipt
~~~

The current FFmpeg adapter is a real end-to-end **reference renderer** but not a general-purpose nonlinear video editor. It has one primary sequential picture track. Multitrack sound, transitions, overlays, separate captions, automation of filming/3D/generative media and evaluation of aesthetics are planned rather than implemented.

## Three distinct artifacts

1. **Blueprint** (schemas/blueprint.schema.json) is reviewed creative authority. It defines typed input slots, story scenes, ordered shot recipes, frame durations, styles, engine hints and declared gates. A smaller model cannot edit it at job runtime.
2. **Job** (schemas/job.schema.json) contains values for declared slots, asset inventory, self-attested rights, source bindings, trim position, frame fit and any human-gate attestation. Unknown keys and undeclared inputs are rejected.
3. **IR/plan** is compiled data, not editable creative direction. It contains shot IDs, inclusive start and exclusive end frames, source mappings, text content, blueprint/job SHA256 hashes and machine/human gate status. A renderer produces media from it.

Blueprint templates are trusted files inside the checked-out repository; they are allowed to be referenced from job directories outside that repository. All media paths are relative to the job's own directory and cannot escape it by traversal or symlink.

### Minimal runnable commands

~~~bash
python -m pip install -r requirements-dev.txt
python -m videogenome validate examples/three-card-explainer/job.json
python -m videogenome compile examples/three-card-explainer/job.json -o /tmp/plan.json
python -m videogenome render examples/three-card-explainer/job.json \
  -o /tmp/out.mp4 --receipt /tmp/receipt.json
~~~

The example produces three full-screen title cards at 24 FPS and 1280x720, for 216 total frames. No API keys, downloads or external media are needed. A second hybrid fixture demonstrates footage with audio, a real still-image hold, and a graphic card.

### Video or image source-binding shape

The job can map shot IDs to previously acquired or generated media:

~~~json
{
  "shot_assets": {
    "live_clip": {"asset": "footage_01", "in_seconds": 1.25, "fit": "cover"},
    "product_still": {"asset": "packshot_02", "fit": "contain"}
  }
}
~~~

The asset inventory must declare each ID, kind, job-relative path, origin description, clearance boolean, license label and evidence reference. These are **self-attested** values, not proof of legal rights.

For v0.1, still_image expects an image file, motion_graphics is programmatically produced, and footage/talking_head/screen_capture/generated_video/3d/animation/composite expect an already-rendered video file. The compiler never pretends to generate video with an AI prompt. Missing media fails preflight.

## Source asset and provider lifecycle (target state)

The future architecture separates an asset requirement from an asset implementation:

~~~
ShotIntent + ReferenceSet + Constraints
    -> CapabilityResolver
    -> Estimate / Budget Approval
    -> ProviderJob (filming | stock | generative | 3D | graphics)
    -> CandidateAssets + provenance
    -> Technical and aesthetic evaluation
    -> Human approval if required
    -> Accepted AssetRecord
    -> Timeline compilation / cache / export
~~~

A proposed provider adapter has capabilities(), estimate(), submit(), poll(), collect(), cancel(), and must declare supported resolution, duration, consistency, camera controls, audio, alpha, text fidelity, model/version and constraints. This interface is **proposed**; do not infer it is available in current code. The framework should fail before costly generation when an adapter cannot meet a hard requirement.

## Rich timeline IR design target

A later multi-layer IR should encode:

- Story/beat graph, shot coverage and edit intent.
- Spatial composition and camera/lighting instructions with realistic adapter capabilities.
- Parallel picture, graphics, effects, masks, subtitle and audio tracks.
- Frame-domain timing with explicit overlap, retiming, fades, J/L cuts and sync points.
- Product, character and world continuity ledgers with asset references.
- Brand-token inheritance with explicit precedence and disallowed overrides.
- Media versions, licenses, model/prompt/seed and source hashes.
- Export aspect variants, localization, accessibility, color and audio targets.
- Executable quality gates with evidence, thresholds and reviewer authority.

OpenTimelineIO is worth evaluating for interchange of editorial structures, but it cannot replace semantic story, provenance or generative-asset plans by itself.

## QA must be evidence-based

| Control | Current behavior | Needed for publishable work |
| --- | --- | --- |
| JSON Schema and semantic validation | enforced | schema compatibility and migration tests |
| Rights | self-attested in job; uncleared is rejected | verified evidence workflow and reviewer identity |
| Media inputs | file exists, sha256, source duration/stream check | codec allowlist, OS sandbox, resource quotas |
| Media output | ffprobe size/duration and output hash | frame drops, loudness, silence and black-frame checks |
| Automated gates from blueprint | recorded as not_evaluated | gate registry, executable tests, evidence and thresholds |
| Human gates | recorded as not_evaluated unless job self-attests | signed approval and publication scope |
| Identity continuity | not evaluated | reference-based assessment plus human checks |
| Narrative/art direction | not evaluated | held-out brief scorecards plus human reviewers |

For safety, **not evaluated** is distinct from passed. A future publication pipeline should block critical unchecked gates. Current output is a development artifact; it is not a production release certification.

## Workflow economics and reproducibility

Render tasks should eventually be content-addressed: hash blueprint, parameters, input assets, engine version and generation references. Regeneration only invalidates dependent shots. Provider requests should have timeouts, retries, cancellation, per-project budgets, and cost per **approved** second of video, not cost per raw generated second.

Stochastic providers need immutable request and response records: provider, model/version, normalized request, reference hashes, generation job ID, time, seed if available, prices, retries and reviewer decisions. The current job stores origin text and hashes, but does not yet implement this full ledger.

## Threat and trust boundaries

Templates and renderer code are trusted, reviewed repository resources. Jobs, embedded copy and media are untrusted data. The CLI does not evaluate model-generated Python or invoke shell strings, and FFmpeg text input is written to temporary files rather than interpolated into command syntax.

This is not a hardened multi-tenant service. Protect public upload/render workers with OS sandboxes, resource limits, timeouts, restricted network access and media validation before deploying them as a service.
