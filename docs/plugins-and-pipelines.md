# Plugins and pipelines: compose your own production stack

VideoGenome splits a production into roles that never leak into each other:

| Who | Owns | Lives in |
|---|---|---|
| Template author | *What* the video needs: typed slots, locked craft, which inputs are **producible** and with which **capability** | `templates/**/blueprint.json` |
| Operator | *Who* produces each capability: providers, endpoints, commands, voices, model licences | pipeline profile (`pipelines/*.json` or your own) |
| Content model or user | The words, choices and any supplied media | job manifest |
| Plugin author | *How* a tool is driven | Python package with entry points, or zero code via the generic adapters |

A job can never choose a provider, a command, an endpoint or a secret. A
blueprint never names a vendor. So the same template renders as a placeholder
animatic on a laptop, with local open-source models on a workstation, or with
real footage from a shoot, and the job doesn't change.

~~~text
job ──► produce ──────────────────────────► compile ──► render ──► analyze ──► gates ──► export
          │ for each missing producible input           renderer   analyzers           exporters
          │ capability ─► profile route ─► provider(s)  (plugin)   (plugins)           (plugins)
          ▼
   generated/ + manifest.json + <job>.produced.json (provenance, rights, cache keys)
~~~

## Quick start

~~~bash
videogenome plugins                    # plugin types, capabilities and where they come from
videogenome pipelines                  # available profiles and how each was verified
videogenome make examples/narrated-slides/job.json --pipeline animatic -o out/slides.mp4
videogenome doctor --pipeline open-source-local    # check every provider of a profile
~~~

`make` = `produce` + `render`. `produce` alone writes `job.produced.json` so you
can inspect, replace or re-generate individual inputs (`--only INPUT`, `--force`).
Generation is cached per input by a hash of the request and provider config.

## Capabilities

A capability is a typed request contract, independent of any tool:

| Capability | Media | Key request fields |
|---|---|---|
| `speech` | audio | `text`, `voice`, `direction`, `language`, `speed`, `max_seconds` |
| `voice_conversion` | audio | `references.source` (previous step), `voice` |
| `music`, `sound` | audio | `prompt`, `negative_prompt`, `duration_seconds` |
| `image` | image | `prompt`, `negative_prompt`, `width`, `height`, `style` |
| `video` | video | `prompt`, `width`, `height`, `fps`, `duration_seconds`, `style` |
| `typing` | video | `text`, `filename`, `language`, `style`, size/fps/duration |
| `render_3d` | image or video | `references.<model input>`, `style`, size/fps/duration |

The set is open. A provider type may declare `capability_specs` for new
capabilities, such as `lip_sync` or `upscale`, and loading the type registers them.
Every request also carries `media` (the file kind expected back), `seed`
(deterministic from job id + input) and `references` (absolute paths of job
assets the blueprint passes along, e.g. a product `.glb`).

**Free-text fields** (`text`, `prompt`, `negative_prompt`, `direction`,
`filename`) may carry untrusted job copy. Adapters must never put them where
they can become code, options, URLs or shell syntax (see Security).

## Blueprint side: producible inputs (schema 0.4.0)

~~~json
"slide_1_voice": {
  "type": "audio", "required": true,
  "description": "Narration; supply a recording or let the pipeline synthesise the script",
  "produce": {"capability": "speech", "voice": "narrator",
              "request": {"text": "{{slide_1_script}}"}}
}
~~~

* `voice` / `style` are **roles**; the profile maps them to concrete voices,
  reference audio, themes or colours.
* `request` values are templates over text inputs only.
* `references` lists other media inputs passed to the provider as files.
* Timing is derived from the locked timeline. Speech must fit its audio
  track's window, or the producer asks to shorten the script. It is then padded
  to the slot. Clips and music must cover their shot or track.
* A supplied input always wins over production. Optional producible inputs
  are skipped when the profile routes no provider for them.
* `model_3d` is a new input and asset kind for reference models (glb, gltf,
  obj, fbx, stl, ply). Renderers never consume it directly.

## Profile side

~~~json
{
  "pipeline_schema": "0.1.0", "id": "my-studio", "extends": "animatic",
  "description": "Studio voices, local images, everything else animatic",
  "verification": "manual 2026-10-11 on studio workstation",
  "providers": {
    "piper": {"type": "command", "config": {
      "capabilities": ["speech"],
      "argv": ["${PIPER_BIN}", "--model", "{voice}", "--output_file", "{output}"],
      "stdin": "{text}", "extension": ".wav",
      "output_rights": {"license": "MIT", "evidence": "voice MODEL_CARD reviewed 2026-10-01"}}}
  },
  "routes": {
    "speech": "piper",
    "image": {"fallback": ["comfy", "placeholder"]},
    "video": {"chain": [{"provider": "wan"}, {"provider": "upscaler", "capability": "video"}]}
  },
  "voices": {"narrator": "${PIPER_VOICES}/en_US-lessac-medium.onnx"},
  "styles": {"terminal_dark": "dracula", "studio_dark": "#111318"},
  "renderer": {"type": "ffmpeg"},
  "analyzers": [{"type": "ffmpeg"}],
  "exporters": [{"type": "subtitles"}, {"type": "poster"}, {"type": "contact_sheet"}]
}
~~~

* **Routes** are a provider name, a `fallback` list tried in order, or a
  `chain` where each step receives the previous output as `references.source`.
  A chain covers patterns like expressive TTS → voice conversion, or image → image-to-video.
* `extends` inherits providers, routes, voices and styles, so you can override
  one capability and keep the rest.
* `${VAR}` expands from the environment when a provider is first used, which
  keeps paths and secret names out of the file. Use `api_key_env` for HTTP keys.
* `output_rights` is the operator's attestation of the output licence (model
  or voice terms). Without it, `produce` refuses that provider's media.
  Providers that report rights per item (`reports_rights`: procedural recipes,
  CC0 retrieval) record each asset's own licence and source page instead.
  `placeholder` output is MIT and always flagged as placeholder.
* `verification` must state honestly how the profile was tested.

Select a profile with `--pipeline ID|PATH`, `VIDEOGENOME_PIPELINE`, and add
search directories with `--pipelines DIR` / `VIDEOGENOME_PIPELINE_PATH`.

## Built-in generic adapters (zero Python)

| Type | Drives | Template values |
|---|---|---|
| `command` | Any CLI that writes a file: Piper, espeak-ng, stable-diffusion.cpp, Type-Simulator, `blender -b` | argv list (no shell), `stdin`, `cwd`, `env`, `defaults`, `extension` (or per-media map) |
| `openai-compatible` | `/audio/speech` and `/images/generations` servers: Kokoro-FastAPI, LocalAI, Speaches… | `base_url`, `model_id`, `api_key_env`, `response_format`, `image_size` |
| `comfyui` | Any exported ComfyUI **API** workflow: FLUX, SDXL, Wan, LTX-Video, Stable Audio… | `workflows.<capability>.file`, `bindings` (`node`, `input`, optional frame transform), `output_node` |
| `mcp` | Tools of any stdio MCP server, e.g. a Blender or ParaView MCP server | `server.argv`, `steps[].tool`, `steps[].arguments` |
| `placeholder` | Labelled slates and silence of the right length (timing previews only) | none |
| `procedural` | Recipes from the catalog (Python/numpy, WebGL/Canvas); also serves `music`/`video`/`image` via `defaults` | `runtimes`, `recipe_dirs`, `defaults.<capability>` |
| `openverse` | CC0 / public-domain images, sounds and music via Openverse | `licenses`, `candidates`, `exclude_terms`, `sources` |
| `wikimedia-commons` | CC0 / public-domain footage, images and audio via Commons (web transcodes) | `allow_licenses`, `skip_restricted`, `max_bytes` |

Placeholders inside templates: `{text}`, `{prompt}`, `{width}`, `{voice}`,
`{references.product_model}`, `{output}`, `{workdir}`, `{profile_dir}`,
`{python}` (the current interpreter), and `{text_file}` / `{prompt_file}` /
`{direction_file}` (free text written to files). A trailing `?` makes a
placeholder optional: `"--model", "{references.model?}"` drops both items when
no model is supplied. A whole-string placeholder keeps its JSON type in MCP and
ComfyUI arguments.

## Writing a plugin in Python

~~~python
from pathlib import Path
from videogenome.plugins import Generated, Provider

class LipSyncProvider(Provider):
    summary = "Lip-sync a portrait to speech"
    capabilities = frozenset({"lip_sync"})
    capability_specs = {"lip_sync": {"media": ["video"], "description": "Animate a face to audio",
                                     "required": ["width", "height"],
                                     "fields": {"width": "integer", "height": "integer", "fps": "integer",
                                                "duration_seconds": "number"}}}
    config_schema = {"type": "object", "properties": {"checkpoint": {"type": "string"}}}

    def check(self):
        return [("OK", "checkpoint found")]

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        face, voice = request["references"]["portrait"], request["references"]["voice"]
        output = workdir / "lipsync.mp4"
        ...  # run the model; raise PluginError on failure, never fake output
        return Generated(output, {"checkpoint": self.config.get("checkpoint")})
~~~

~~~toml
[project.entry-points."videogenome.providers"]
lipsync = "my_package.lipsync:LipSyncProvider"
~~~

The other extension points work the same way:

| Group | Base class | Contract |
|---|---|---|
| `videogenome.providers` | `Provider` | `generate(capability, request, workdir) -> Generated` |
| `videogenome.renderers` | `Renderer` | `unsupported(plan) -> [features]` (refuse, never fake), `render(plan, job_dir, output) -> report` |
| `videogenome.analyzers` | `Analyzer` | `measure(output, plan) -> {"metrics", "not_applicable", "details"}`; any metric can back a gate `check` |
| `videogenome.exporters` | `Exporter` | `export(plan, output, protected) -> {kind: path}` |

For tests, notebooks and embedding, `videogenome.plugins.register(kind, name, cls)` registers a type in-process.

## Security rules every adapter follows

* Profiles are trusted operator configuration; jobs, blueprint copy and model
  output are untrusted data.
* No shell anywhere. Executables are fixed in the profile (`argv[0]` cannot be a
  placeholder). Free text enters a CLI only through stdin, a file, or an
  option value (`"--prompt", "{prompt}"` or `"--prompt={prompt}"`). A free-text
  field as a bare positional argument is rejected when the profile loads.
* MCP arguments named like code (`code`, `script`, `command`, `python`, `shell`…)
  may not contain free-text placeholders. A profile may call a code-execution
  tool only with an operator-owned `script_path` plus data `args`, as the
  Blender profile does.
* HTTP adapters only accept `http(s)` endpoints from the profile and read keys
  from named environment variables.
* Typed code is display text: the Type-Simulator profile always passes `--no-run`.
* Every generated asset records providers, models, request hash, step outputs
  and the operator's rights attestation. Placeholder media is flagged in the
  receipt and the CLI.

## Verified compositions

| Composition | Profile | Evidence |
|---|---|---|
| Placeholders for every capability | `animatic` | CI renders the narrated, typing and turntable examples |
| Piper narration + placeholder pictures | `open-source-local` | Manual run 2026-10-11: 3 lines, 4.0–4.25 s each, conformed to 5.5 s slots, −16 LUFS master |
| Type-Simulator typing reel | `open-source-local` | Manual run 2026-10-11: 9-line Python snippet, highlighted, `--no-run` |
| Blender turntable from a `.glb` | `open-source-local` | Manual run 2026-10-11: Blender 5.1.1 EEVEE, 120 frames at 1080² |
| Same turntable through blender-mcp-server | `blender-mcp` | Manual run 2026-10-11: `blender_python_exec` headless, 27 tools listed by `doctor` |
| Kokoro-FastAPI, LocalAI, ComfyUI, stable-diffusion.cpp, espeak-ng | respective profiles | Protocols covered by tests against local fakes; **not** run against live servers |

See [open-source stack](open-source-stack.md) for more tools and how to plug them in.
