# Changelog

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
