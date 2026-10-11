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
- Define technical and human review gates; never declare an unimplemented aesthetic check as executed.
- Provide a sample job and reproducible media evidence if this template is renderable by an available adapter.
- Add test cases for missing inputs, incompatible assets, duration consistency and expected output.

Templates requiring unavailable providers may be contributed **as blueprints**, but documentation must state they do not render with the current adapter without independently produced media.

## Smaller model: template-filler role

- First discover templates with python -m videogenome catalog, then inspect the chosen template.
- If useful, generate a job skeleton with python -m videogenome scaffold TEMPLATE_ID -o job.json.
- Fill only blueprint-defined input slots. Do not edit style tokens, story structure, cameras, direction, quality gates, code or schema.
- Map actual local media paths through the assets dictionary and bind pre-produced media to shot IDs through shot_assets.
- Never invent a license, release, asset-origin record, approval, factual testimonial or product evidence.
- If essential input or consent is missing, report the missing requirement rather than fabricating it.
- Validate with python -m videogenome validate JOB.json before trying to render.
- Never place arbitrary Python, JS, shell commands or provider secrets into production job fields.
- Never mark human quality gates approved without a genuine authorized approval.

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
