# Contributing reusable video-production expertise

We welcome contributions covering filmed, generated, animated, educational, social, documentary, cinematic, 3D and hybrid videos. Prefer a **narrow, working, well-tested slice** over a large folder of aspirational contracts.

## A template contribution

Submit a new versioned blueprint under templates/<category>/<recipe>/blueprint.json. Describe audience/intent, narrative logic, allowed content slots, locked design decisions, required shot media, required providers, aspect/frame format and quality gates. Include example text and media provenance. If an engine can execute it, provide a sample production job and preview evidence.

A good template author should be able to explain:

1. Which professional decisions are embodied in the recipe, and why.
2. Which exact choices the cheaper model is allowed to make.
3. Which source media rights and factual constraints are mandatory.
4. How to detect poor results (technical, narrative, visual, semantic and rights).
5. Which engines can and cannot execute the recipe, and which features degrade on fallback.
6. How the template performs on at least two contrasting briefs.

Do not provide rights assertions, synthetic testimonials or real-person consent unless verifiable and authorized. Keep private personal data and paid/unlicensed media out of the public repository.

## A code or adapter contribution

Preserve compatibility with earlier blueprint versions or provide migration tooling. Add unit tests for validation and integration tests that produce an actual media artifact whenever possible. Adapter changes should show media hashes, source dependency behavior, fidelity limits, deterministic output constraints, failure modes and costs where applicable.

Run:

~~~bash
python -m pip install -r requirements-dev.txt
python -m tools.validate
python -m unittest discover -s tests -v
~~~

Use GitHub Actions artifacts to inspect the produced MP4 visually. Do not merge based only on JSON or Python test status; aesthetic and narrative quality still need human review.

## Review rubric

| Area | Required reviewer evidence |
| --- | --- |
| Reusability | two different input briefs work without editing locked art direction |
| Design | typography, composition, motion/footage and branding feel consistent |
| Narrative | hook, sequence, clarity, pacing and completion match intent |
| Media truth | generated or filmed footage is honestly identified |
| Fidelity | products, characters, UI, logos and testimonials remain accurate |
| Accessibility | captions, contrast and safe zones meet delivery context |
| Rights | source, license, consent and claims have inspectable references |
| Engineering | reproducible render, validation, failure cases, provenance |
| Economics | estimates and retries are visible when providers add cost |

Avoid approving a template based only on a cherry-picked pretty frame. View full playback and try adversarially long inputs and mixed asset qualities.

## Compatibility and releases

The original creative blueprint is versioned separately from the production job contract and normalized IR. Template version upgrades do not automatically migrate live jobs; the job pins a specific version. Breaking contract changes require a schema version and explicit compatibility policy.

This is an early experimental repository. Proposed provider interfaces and advanced timeline features in documentation are not shipped APIs.
