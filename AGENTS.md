# Instructions for agents working in VideoGenome

VideoGenome is a **universal video-production expertise repository**, not solely a motion-graphics project. Blueprints must be renderer-independent and truthful about capability limits.

## Expert template author role

- Start from docs/video-ontology.md and docs/production-pipeline.md.
- Treat purpose, narrative, artistic treatment, acquisition method, and delivery as independent axes.
- Contribute a reusable recipe, not a one-off branded video masquerading as a template.
- Identify which decisions are locked; expose only safe typed input slots.
- Use schemas/blueprint.schema.json and pass python -m tools.validate.
- Distinguish shot kinds accurately: filmed footage is not generated footage; a 3D render is not a live recording.
- Include accurate and verifiable provenance, licenses and rights/consent expectations.
- Define technical and human review gates; never declare an unimplemented aesthetic check as executed. Attach a machine check (see docs/motion-design-and-delivery.md) only for metrics the renderer actually measures.
- Provide a sample job and reproducible media evidence if this template is renderable by an available adapter.
- Add test cases for missing inputs, incompatible assets, duration consistency and expected output.

Templates requiring unavailable providers may be contributed **as blueprints**, but documentation must state they do not render with the current adapter without independently produced media.

## Smaller model: template-filler role

- First discover templates with python -m videogenome catalog (add --self-contained for text-only templates), then inspect the chosen template.
- Reference templates by catalog id in the job's template field, never by copying or editing a blueprint.
- If useful, generate a job skeleton with python -m videogenome scaffold TEMPLATE_ID -o job.json.
- Fill only blueprint-defined input slots. Do not edit style tokens, story structure, cameras, direction, quality gates, code or schema.
- Map actual local media paths through the assets dictionary and bind pre-produced media to shot IDs through shot_assets.
- Never invent a license, release, asset-origin record, approval, factual testimonial or product evidence.
- If essential input or consent is missing, report the missing requirement rather than fabricating it.
- Validate with python -m videogenome validate JOB.json before trying to render.
- Inputs marked producible may be left out; run `videogenome produce` or `make` with the pipeline the operator chose. Never pick, add or edit a pipeline profile, provider, command, endpoint or voice yourself.
- Never claim generated or placeholder media is real footage, a real voice or a real product; receipts flag placeholders and these must not be published.
- Never place arbitrary Python, JS, shell commands or provider secrets into production job fields.
- Never mark human quality gates approved without a genuine authorized approval.
- If compile reports that copy does not fit, shorten the copy; never ask for a smaller font or edit the layout.
- Render exit status 3 means an automated gate failed: report the failing metric from the receipt, do not suppress it.

## Recipe author role (procedural visuals and audio)

- Put code and a recipe.json in recipes/<area>/<name>/; follow docs/procedural-recipes.md.
- Every parameter needs a bounded type, a default and a description; ship named presets that look and sound good.
- Derive all randomness from spec.seed (and the frame index); output exactly the requested frames or samples.
- Review your own output: contact sheets for visuals; loudness, band balance and spectrograms for audio. Never claim it "sounds good" from measurements alone.
- Browser recipes must work offline: no CDNs, fonts or network.

## Template-filler: tweaking procedural media

- Choose among enum inputs (moods, energies) a template exposes. If a template lets you set recipe params, keep values inside the recipe schema shown by `videogenome recipes --json`.
- Preview with `videogenome recipe ID --preset P --set key=value -o preview.mp4` before rendering a whole job.

## Plugin author role (providers, renderers, analyzers, exporters)

- Implement the interfaces in videogenome/plugins.py and publish them through entry points; do not edit core code to add a vendor.
- Prefer the generic command, openai-compatible, comfyui or mcp adapters plus a pipeline profile when they suffice.
- Treat request free-text fields as untrusted: never place them in shell strings, code, URLs or bare CLI positionals.
- Fail loudly with PluginError; never return a substitute file. Report checks via check() so `videogenome doctor --pipeline` is truthful.
- Ship a profile only with an honest `verification` field; do not invent `output_rights`.

## Renderer and adapter author role

- Treat manifests and media as untrusted data. Never execute job text or construct shell commands from untrusted strings.
- Keep engine-specific code behind adapters and keep the compiled creative IR portable.
- Use deterministic frame timing and explicit source hashes.
- Errors must be explicit: a capability-limited provider must refuse an unsupported feature, not quietly fake it.
- Add working integration tests, provenance and quality evidence for any new claim of renderer support.
- Maintain clear boundaries between creative intent, producer planning, media generation, assembly and assessment.

## Minimum verification before PR

~~~bash
python -m pip install -r requirements-dev.txt
python -m tools.validate
python -m unittest discover -s tests -v
python -m videogenome render examples/three-card-explainer/job.json \
  -o /tmp/videogenome-demo.mp4 --receipt /tmp/videogenome-receipt.json
~~~

CI uses FFmpeg to render a real demo and attach the result for visual review. A successful render is not publication or legal approval.
