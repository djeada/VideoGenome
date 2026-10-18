# Changelog

## Unreleased

### Fixed
- MCP sessions survive malformed JSON-RPC requests and report protocol errors;
  tool arguments now enforce the advertised schemas before dispatch.
- Studio rejects malformed JSON, invalid body lengths, unsupported controls,
  non-finite numbers and mistyped render settings before queuing work.
- Video playback supports suffix and open-ended byte ranges, returns 416 for
  unsatisfiable ranges, and streams files in bounded chunks. HEAD requests
  return metadata without reading the video.
- Workspace HTML, HTM and SVG responses disable scripts and forms; filenames
  containing spaces, Unicode, `#` or `%` produce usable download URLs.
- Installed wheels include sample jobs and brief suites, restoring Studio
  sample copy and library previews. CI checks the installed package outside
  the source checkout.
- Input checks retain supplied null/empty values for type validation and
  recognize required blueprint defaults. Numeric slots must be finite;
  capture validates frame rate, duration, dimensions, seed and still time.
- Run history counts readable summaries rather than incomplete run folders
  and skips corrupt summaries and symlinks outside the workspace.

## 0.7.0 — a library of video classes, three cockpits, code that runs unmodified

### Added
- **Genome library** (`genomes/<id>/genome.json` + `prompt.md`, `schemas/genome.schema.json`):
  every class of video with a level derived from what exists: **template**
  (brief to video), **code** (recipes with params) or **prompt** (an authoring
  prompt for an agent). `videogenome library`, `videogenome genome ID [--prompt]`.
  30 classes: 24 ready to fill, 2 ready code, 4 prompt only.
- **Scene recipes and templates for the classes model-made video galleries are
  full of**, authored to a shared quality bar and reviewed frame by frame:
  stat reveals and animated charts, an app-launch UI promo, event teasers (3-2-1
  and days-to-go), how-it-works diagrams, history timelines, quotes over
  generative art (9:16 and 1:1), a tempo-locked beat visualizer, route maps on
  Natural Earth coastlines, browser-only code reveals (16:9 and 9:16) and motion
  showreels (16:9 and 9:16), each with sample jobs and bench briefs.
- **Studio** (`videogenome studio`): a local web UI to browse the library, fill a
  template from a brief or by hand with live checks, render and review, tune any
  recipe's params, render your own HTML, and connect agents. Token-protected,
  localhost-only, workspace-confined. `videogenome previews` renders library previews.
- **MCP server** (`videogenome mcp`): agents read slot contracts, write the copy,
  `check_inputs`, `render` (contact sheet returned as an image), preview recipes,
  `capture_html` their own code, and use every genome's authoring prompt as an MCP prompt.
- **Run code unmodified**: pages are served from a virtual origin (ES modules,
  import maps, `fetch` of sibling files; everything else blocked); Web Audio is
  rendered offline in lockstep with the frames and muxed in sync; `--click` for
  click-to-play pages. Shared libraries at `/_lib/`: the `vg-scene` toolkit and a
  vendored three.js 0.169 (MIT, checksummed). `videogenome recipe-new` scaffolds
  2D or three.js scenes.
- Blueprint schema additions: `grounded_with` (a verbatim value must sit next to
  its label in the brief), `whole_quote` (a quote must be the entire quotation),
  verbatim number inputs grounded in the brief's numbers.

### Changed
- Writers must return every required slot; verbatim slots may be `null` and
  ungrounded ones become *missing* (exit 4) rather than *failed*. Written slots
  are listed before verbatim ones, short verbatim values match whole words only
  (scale units such as `M` match "million"), candidate phrases drop sentence
  openers and connectors, and incomplete drafts never keep rejected values.
- `videogenome validate` accepts jobs whose producible media is still to be
  produced and lists it; rendering a pending plan is refused.
- Optional whole-slot items in produced request arrays are dropped when the slot is
  left out, so templates can map `value_1..value_6` onto variable-length recipe lists.
- Validation is fast again: schema meta-validation and recipe discovery are cached
  (the full library validates in under a second).
- Recipe provenance hashes include the shared libraries a recipe uses.

## 0.6.0 — from one-off prompts to a system: briefs, writers and code-animated scenes

Galleries of model-made videos show what a frontier model can write once as
code. This release makes that class of result repeatable: the animation becomes
a deterministic recipe, the blueprint locks it, and any model fills a brief.

### Added
- **Writers and `videogenome fill`**: a new plugin kind (`videogenome.writers`)
  with `openai-chat` (Ollama, llama.cpp, vLLM, hosted APIs; JSON-schema
  constrained output) and `command` (prompt on stdin) adapters. Profiles declare
  a `writer`. `fill` turns a brief into a job using slot contracts derived from
  the blueprint: title-card capacity, caption reading speed, narration words per
  locked second, scene-recipe text limits and enums. Replies are checked by the
  compiler and by the renderer's glyph measurement (`Renderer.check_copy`), and
  problems go back with the exact value. Writes `<job>.fill.json`.
- **Verbatim grounding and honest refusals**: input `fill` policy (`write`,
  `verbatim`, `never`); verbatim slots must match the brief, candidate phrases
  are extracted for the writer, and ungrounded proposals become *missing*.
  Missing required facts end with exit status 4 and a draft job.
- **`copy_examples`** in blueprints (schema 0.5.0): expert-written brief and
  ideal values, shown to the writer and validated like a reply.
- **`videogenome create`**: brief to finished video in one command (fill,
  produce, render, gates, review). Measured narration that overruns its slot
  (`CopyTooLong`) goes back to the writer to shorten exactly that copy.
- **`videogenome bench`**: fill rate, first-attempt rate, attempts, writer time
  and honest-refusal rate over a brief suite; `--render` also gates every video.
  `examples/briefs/smoke.json` has twelve briefs, including two that lack
  facts and an injection attempt.
- **Virtual clock for browser rendering**: `"timing": "clock"` recipes and the
  new **`videogenome capture`** render ordinary animation code
  (requestAnimationFrame, performance.now, Date, timers, CSS/WAAPI) frame-exactly
  and byte-reproducibly. Pages may load only files beside them.
- **Scene recipes**: `scene.kinetic-type` (kinetic typography with an
  accent-circle wipe), `scene.steps` (process explainer with check marks and
  recap) and `scene.title-sting` (fly-in brand reveal with impact, sweep and
  tagline), each with presets and measured text fitting.
- **Templates**: `social.kinetic-promo`, `educational.steps-explainer` and
  `commercial.title-sting`, with sound cues on each scene's beats and sample jobs.
- **Review page** exporter (`<output>.review.html`, on by default): video,
  measurements, gates with evidence, pending human decisions, provenance and the
  brief/writer behind the copy. Exporters gain an optional `finalize(receipt)`.
- Profile `procedural-writer` (procedural media + Qwen2.5-3B on Ollama).

### Changed
- Copy examples and fill policies on the text templates (vertical-tips 0.2.0,
  title-card-sequence 0.3.0, narrated-slides, cc0-documentary, code-typing-reel,
  product-turntable, captioned-explainer 0.2.0), and verbatim-only testimony,
  names and calls to action in `social.ugc-testimonial` 0.2.0 (now with caption
  cues) and `commercial.cinematic-product-reveal` 0.2.0. Example jobs pin the new versions.
- The compiler exposes `copy_issues()` to report every copy problem at once.
- Browser recipes are confined to their own directory instead of any `file://` URL.

## 0.5.0 — procedural media, CC0 sourcing and a mix that holds up

### Added
- **Procedural recipe layer** (`recipes/`, `schemas/recipe.schema.json`,
  `videogenome.procedural`): deterministic generators with JSON-Schema params,
  defaults, presets and seeds. They run as **Python** (numpy/scipy) or **browser**
  (WebGL / Canvas in headless Chromium, offline, seeded) recipes. Nine recipes:
  `visual.aurora`, `visual.bokeh`, `visual.dot-wave`, `visual.shader-gradient`,
  `visual.flow-lines`, `audio.ambient-pad`, `audio.lofi-beat`, `audio.pulse`,
  `audio.transition`.
- Recipe toolkits: `kit` (writers, OKLab palettes, noise, dithering, parallel
  frames), `dsp` (theory, oscillators, filters, reverb, delay, BS.1770
  loudness matching FFmpeg, band balance, mastering), `instruments` and `shapes`.
- `procedural` capability and provider (MIT, per-item provenance with recipe hash
  and resolved params). `videogenome recipes` and `videogenome recipe ID --preset
  --set k=v` let a person or model preview and tweak parameters.
- **CC0 / public-domain retrieval**: `openverse` (images, sounds, music) and
  `wikimedia-commons` (footage, images, audio) providers. They filter licences
  per item, skip restricted items and record title, creator and source page as
  rights evidence. Providers can now report rights per item (`reports_rights`).
- **Kokoro-82M narration** wrapper (`pipelines/kokoro/kokoro_tts.py`).
- Profiles: `procedural` (CI), `cc0-stock`, `piper-local`; `open-source-local`
  now uses Kokoro + CC0 + procedural.
- Schema 0.4.0 additions: `title_card.background_input` / `background_dim`
  (moving backgrounds behind cards, dimmed in RGB), still-image `motion` (Ken
  Burns via supersampled zoompan), timeline `ducking` (frame-exact gain curves
  under other tracks), input `enum` and `default`, nested and typed request templates.
- Template `educational.cc0-documentary`; existing templates now use procedural
  backdrops, music beds, ducking, motion and transition whooshes.

### Fixed
- **True-peak overs after AAC encoding.** The master now measures the decoded
  file and re-encodes with corrective gain until it is under the ceiling. The
  previous code reel measured +0.75 dBFS.
- Placeholder audio is now silence of the right length. It was tones and beeps
  that loudness mastering pushed up to full level.
- Captions use the template's pinned typeface with a lighter box.
- Partially failed `produce` runs keep the inputs they finished.
- Request text keeps line breaks and indentation, so code is typed correctly.
- Card background scrims dim in RGB; the YUV `drawbox` scrim turned colours brown.
- Blender turntable colours are converted from sRGB to linear (they rendered far too light).
- Openverse requests stay within the anonymous 20-results page limit.
- Retrieval relaxes long prompts into shorter queries, ranks by title relevance,
  and skips news, interview and portrait material (title, description, artist and credit).
- `produce` reports why each fallback happened.

## 0.4.0 — composable, plugin-based pipelines

### Added
- **Four extension points** with Python entry points: `videogenome.providers`,
  `videogenome.renderers`, `videogenome.analyzers`, `videogenome.exporters`;
  plus `plugins.register()` for in-process use. `videogenome plugins` lists them.
- **Open capability registry**: `speech`, `voice_conversion`, `music`, `sound`,
  `image`, `video`, `typing`, `render_3d`. Plugins may declare new capabilities.
- **Pipeline profiles** (`schemas/pipeline.schema.json`): providers, routes
  (single, `fallback`, `chain`), voice and style roles, renderer, analyzers and
  exporters; `extends`, `${ENV}` expansion and an honest `verification` field.
  Selected with `--pipeline` or `VIDEOGENOME_PIPELINE`. Listed by `videogenome pipelines`.
- **Generic adapters**: `command` (argv, no shell, free-text placement rules,
  optional placeholders), `openai-compatible` (speech and images), `comfyui`
  (API workflows with node bindings and frame transforms), `mcp` (stdio
  JSON-RPC tool calls, code-argument guard) and `placeholder` (labelled
  animatic media).
- **`produce` and `make` commands.** Producible inputs (schema 0.4.0) are built from
  text slots, routed, conformed to locked timing (speech padded or rejected
  as too long), cached per request, and recorded with provenance and the
  operator's rights attestation. A supplied input always wins.
- `model_3d` input and asset kind for reference models; auto-binding of shots
  to their single media input.
- **Shipped profiles**: `animatic` (CI), `open-source-local` (Piper,
  Type-Simulator, Blender; manually verified), `blender-mcp` (manually
  verified), and examples for Kokoro-FastAPI, LocalAI, ComfyUI,
  stable-diffusion.cpp and espeak-ng.
- `pipelines/blender/turntable.py`: headless product turntable that works with
  `blender -b` or an MCP server's `blender_python_exec`.
- **Templates**: `educational.narrated-slides`, `educational.code-typing-reel`,
  `commercial.product-turntable`, with example jobs and
  `tools/create_product_model.py` (a procedural `.glb`).
- Gate checks accept any metric an analyzer reports. Metrics with no analyzer
  stay `not_evaluated` with a reason. Receipts record the pipeline and flag
  placeholder media.
- Docs: `docs/plugins-and-pipelines.md`, `docs/open-source-stack.md`.

### Changed
- Rendering is composed by `videogenome.pipeline.run_render`: renderer,
  analyzers, gates, exporters. `render()` keeps its signature. Receipt
  `measurements` now carries `not_applicable`, `sources` and per-analyzer `details`.

## 0.3.0 — usable product release

### Added
- **Installable CLI.** `pip install .` provides a `videogenome` command; schemas
  and reviewed templates ship inside the wheel. `videogenome --version`.
- **Templates by id.** Jobs may set `"template": "social.vertical-tips"` and work
  from any directory. `scaffold` now writes the id and lists only required inputs.
- **External template directories** trusted by the operator via `--templates DIR`
  or `VIDEOGENOME_TEMPLATE_PATH`; ambiguous ids are rejected.
- **`videogenome doctor`** checks Python, jsonschema, FFmpeg/ffprobe, required
  filters, `drawtext` baseline alignment, encoders, fontconfig and every catalog font.
- **`catalog --self-contained` / `--table`**, plus `duration_seconds`,
  `self_contained`, `machine_checked_gates` and `style` in catalog entries.
- **Schema 0.3.0** (superset of 0.2.0):
  - `style.title_card`: locked font, weight, alignment, size range, line limit,
    safe margins, palette-checked colours, accent rule, kicker size, entrances.
  - `direction.kicker_template` for small accent lines above headlines.
  - `timeline.transitions` (`crossfade`, `dip`) and programme `fade_in_frames` /
    `fade_out_frames`; programme length and shot start frames never change.
  - `output.loudness` (two-pass EBU R128) and `output.poster_frame`.
  - `quality_gates[].check` with `integrated_lufs`, `true_peak_dbtp`,
    `black_seconds`, `blank_seconds`, `longest_blank_seconds`, `longest_silence_seconds`.
- **Copy fitting.** The compiler picks the largest locked size that fits and balances
  line breaks, rejecting copy that cannot fit. The renderer pins one font file
  and measures real glyphs, shrinking further only when needed.
- **Executed measurements** on every render (loudness, true peak, LRA, black,
  blank picture, silence) and machine-checked gate results with evidence.
  `render` exits 3 when an automated gate fails.
- **Sidecars**: SRT and WebVTT captions, poster frame and per-shot contact sheet,
  all hashed in the receipt.
- New renderable template **`social.vertical-tips`** (9:16, 13.5 s, -14 LUFS) and
  example job; **`educational.title-card-sequence` 0.2.0** upgraded to the new
  typography with dips and a blank-picture gate.
- Receipt now records renderer/FFmpeg versions, the pinned font (with
  substitution warning), executed title layout, picture transitions and
  loudness normalisation details.

### Changed
- Every render runs one finishing pass, with PCM audio between intermediate clips, for both
  v0.1 and v0.2 plans. Video-segment audio is sample-exact and AAC is encoded once.
- Legacy (0.1/0.2) title cards keep their look but wrap long copy instead of
  running off the frame, and reject copy that cannot fit.
- Blueprint validation moved to `videogenome.blueprint`; `tools/validate.py`
  remains as the CLI entry point and compatibility import.
- Optional audio inputs that the job omits now skip their audio track.
- `scaffold` refuses to overwrite an existing file. Render output must be `.mp4`.
