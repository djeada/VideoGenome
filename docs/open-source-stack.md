# Open-source stack: tools you can plug in today

This is a map of open-source tools for each capability and the adapter that drives
each one. **Verified** means it was run end to end through VideoGenome on the
date shown. **Example** means a profile or snippet exists but has only been tested
against a protocol fake. **Recipe** means guidance only.

Licences change and often differ between code and weights. The notes below are
pointers, **not legal advice**: read the model card, then record your own
`output_rights` in the profile. VideoGenome refuses a provider's media until
you do.

## Speech (`speech`, `voice_conversion`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | `command`, profile `open-source-local` | **Verified** 2026-10-11 (piper-tts, `en_US-lessac-medium`, CPU, ~1.5 s per line) | Fast, offline, many languages; each voice has its own licence in its MODEL_CARD |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via `pipelines/kokoro/kokoro_tts.py` | `command`, profile `open-source-local` | **Verified** 2026-10-11 (CPU, voice `af_heart`) | Natural narration; install its venv at a short path, because libespeak-ng fails silently on data paths over ~160 characters |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) | `openai-compatible`, profile `kokoro-fastapi` | Example | Weights published as Apache-2.0. A peer session measured ~2.5× real time on CPU. Clean but flat delivery: good for narration, weak for drama |
| Kokoro in Python (`pip install kokoro soundfile`) | `command` + a small wrapper script | Recipe | `KPipeline(lang_code='a')`, voices like `am_fenrir`, 24 kHz. Phoneme overrides via `[Word](/phonemes/)` |
| [Qwen3-TTS](https://github.com/QwenLM) 1.7B VoiceDesign | `command` + wrapper (`--text-file --instruct-file --out`) | Recipe | Very expressive; follows `direction` ("numb whisper"). Identity changes on every call, so chain it with voice conversion. Needs CUDA (RTX 50xx: torch cu128 wheels) |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) VC | `command` + wrapper (`--source --ref --out`), chained after a speech step | Recipe | MIT. Holds a character's identity (speaker similarity 0.5–0.77 in peer tests). Adds a Perth watermark. Install `--no-deps` on new torch |
| [espeak-ng](https://github.com/espeak-ng/espeak-ng) | `command`, profile `espeak-ng` | Example | Robotic formant voice, 100+ languages, tiny install; good for drafts |
| LocalAI, Speaches, openedai-speech | `openai-compatible`, profile `localai` | Example | Any server exposing `/v1/audio/speech` |

The expressive-character recipe from the Standard-of-Iron drama work maps to a chain:

~~~json
"routes": {"speech": {"chain": [
  {"provider": "qwen_voicedesign"},
  {"provider": "chatterbox_vc", "capability": "voice_conversion"}]}},
"voices": {"narrator": "${VOICES}/narrator_ref.wav"}
~~~

Expressive takes run longer than flat TTS (an episode grew from 8:53 to
10:16). Locked slots reject over-long speech, so either write shorter lines or
use a template with longer windows. Audio-driven re-timing is on the roadmap.

## Openly licensed media (CC0 / public domain)

| Source | Adapter | Status | Notes |
|---|---|---|---|
| [Wikimedia Commons](https://commons.wikimedia.org) | `wikimedia-commons`, profile `cc0-stock` | **Verified** 2026-10-11 (footage) | Keeps only CC0 / public-domain items, skips anything with restrictions, prefers 720p web transcodes. Licences are mixed, so filtering matters |
| [Openverse](https://openverse.org) | `openverse`, profile `cc0-stock` | Search and licence filter tested against live API and fixtures; anonymous requests are limited to 20 results per page | Flickr and museum images, Freesound CC0 audio. Relevance depends on search words |

Keyword search over open archives finds *something* real. Whether it matches
the narration is a human gate (`footage_relevance` in the documentary
template). When no CC0 match exists, the profile falls back to a procedural
visual and records that.

## Procedural (code-generated)

Nine MIT recipes ship in `recipes/`: aurora, bokeh, dot-wave, WebGL mesh
gradient and Canvas flow-lines visuals, plus ambient, lo-fi and pulse beds and
transition SFX. See [procedural recipes](procedural-recipes.md).

## Typing and screen simulation (`typing`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| [Type-Simulator](https://github.com/djeada/Type-Simulator) `--mode reel` | `command`, profile `open-source-local` | **Verified** 2026-10-11 (v2.2.0, headless, 1080×1920) | Renders vim-style typing with syntax highlighting, cursor and key sounds, MIT. Always pass `--no-run` so job code is never executed; `--music none` lets the blueprint own the soundtrack. Length is approximate, so the profile adds a 1 s `duration_margin_seconds` |
| [VHS](https://github.com/charmbracelet/vhs) | `command` + a tape template | Recipe | Terminal recordings from `.tape` scripts; build the tape from `{text_file}` in a wrapper |
| [asciinema](https://asciinema.org) + [agg](https://github.com/asciinema/agg) | `command` | Recipe | Real terminal sessions to GIF; convert to MP4 with FFmpeg |

## Images (`image`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | `comfyui`, profile `comfyui` (bundled SD 1.5 API workflow) | Example | Hosts FLUX.1-schnell (Apache-2.0), SDXL (OpenRAIL++-M), SD 3.5 (Stability community licence) and more |
| [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) | `command`, profile `stable-diffusion-cpp` | Example | Single binary, CPU, Vulkan or CUDA, GGUF models |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI), [Fooocus](https://github.com/lllyasviel/Fooocus) | `command` or a Python provider | Recipe | Useful when a team already runs them |
| LocalAI | `openai-compatible`, profile `localai` | Example | `/v1/images/generations` |

## Video (`video`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| Wan 2.1 / 2.2 | `comfyui` (export your workflow with *Save (API)*) | Recipe | Bind duration with `{"transform": "frames", "frame_multiple": 4, "frame_offset": 1}` (4n+1 frames) |
| [LTX-Video](https://github.com/Lightricks/LTX-Video) | `comfyui` or `command` | Recipe | Fast; uses 8n+1 frame counts (`frame_multiple: 8, frame_offset: 1`) |
| HunyuanVideo, CogVideoX, Mochi | `comfyui` | Recipe | Check each model's licence and acceptable-use terms |
| Image → video chain | `chain` route: `image` step, then `video` step reading `references.source` | Recipe | Gives stable key frames and controllable motion |

## 3D (`render_3d`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| [Blender](https://www.blender.org) + [`pipelines/blender/turntable.py`](../pipelines/blender/turntable.py) | `command`, profile `open-source-local` | **Verified** 2026-10-11 (Blender 5.1.1, EEVEE, headless) | Imports glb/gltf/obj/fbx/stl/ply, normalises scale, three-point light rig, 360° orbit, still or MP4 |
| [blender-mcp-server](https://github.com/djeada/blender-mcp-server) | `mcp`, profile `blender-mcp` | **Verified** 2026-10-11 (v0.2.0, `blender_python_exec`, headless transport) | The same script runs through MCP: an operator-owned `script_path` plus data `args`, never job code. The headless transport bypasses the add-on's safety settings, so treat that server as fully privileged |
| ParaView via [paraview-mcp-server](https://github.com/djeada/paraview-mcp-server) | `mcp` | Recipe | Scientific visualisation renders as `video` or `render_3d` |
| Text-to-3D models (TRELLIS, Hunyuan3D) | Python provider producing a `model_3d` that a turntable step then renders | Recipe | Needs `model_3d` outputs from producers, which is planned |

## Music and sound (`music`, `sound`)

| Tool | Adapter | Status | Notes |
|---|---|---|---|
| [ACE-Step](https://github.com/ace-step/ACE-Step) | `comfyui` or `command` | Recipe | Song and instrumental generation |
| [Stable Audio Open](https://huggingface.co/stabilityai/stable-audio-open-1.0) | `comfyui` | Recipe | Short loops and sound effects; Stability community licence |
| MusicGen (AudioCraft) | `command` + wrapper | Recipe | Weights are CC-BY-NC, so not for commercial output |
| Your own library | Supply files as job assets | Always works | Licensed or original music is often the best answer |

## Analysis (future gates)

| Tool | Analyzer idea | Notes |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | `word_error_rate` of narration against the script | Peer tip: decode audio yourself (16 kHz float32 array); file decoding broke with some PyAV versions |
| [SpeechBrain ECAPA](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | `speaker_similarity` to a character reference | Combine with WER to pick the best of N takes |
| [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) | Loudness per stem | The built-in FFmpeg analyzer already covers the programme |

Any of these becomes a gate by registering an `Analyzer` that reports the
metric. A blueprint gate `{"check": {"metric": "word_error_rate", "max": 0.1}}`
is then evaluated. Until such an analyzer is configured, the gate stays
`not_evaluated`.
