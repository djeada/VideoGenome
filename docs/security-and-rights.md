# Security, consent, media rights and approvals

## Trust model

The **reviewed repository** owns template code, creative decisions, schemas and adapters. The **smaller model** provides a job with typed values and previously cleared local media. A **renderer** treats the job as untrusted data. A **human publisher** retains responsibility for authenticity, creative judgment, brand safety and lawful distribution.

The reference compiler limits job keys, rejects unknown input variables and missing media, confines asset paths to the job directory even through symlinks, and verifies asset hashes during rendering. Templates must be existing files inside the trusted repository. A proposed future signed template registry would define authoritative versions and dependencies.

Subprocesses receive argv arrays rather than shell-constructed commands. Untrusted title copy is stored as a text file passed to FFmpeg drawtext, not interpolated into filter syntax. Drawtext expansion is disabled so percent signs, backslashes and expression-like copy such as `%{eif:1+1:d}` remain literal text. This prevents many command-injection paths, but it is **not** a hardened media-processing sandbox.

## Threats and controls

| Threat | Existing protection | Required before public multi-tenant service |
| --- | --- | --- |
| Malicious text and prompt injection | no text execution, declared slot binding only | tool permission scopes, model prompt/data separation |
| Path traversal or symlink escape | job-local confinement for media; trusted templates | OS sandbox and safe-open policy |
| FFmpeg command injection | no shell, textfile-based graphics | pin FFmpeg, block dangerous protocols/codecs |
| Crafted media/zip bombs | file probe and duration check | resource quotas, timeouts, file size and codec allowlist |
| Disallowed media use | evidence reference and self-attested clearance | verified licenses and media release workflow |
| Voice/identity misrepresentation | no fabricated speech generated here | consent verification, provenance, impersonation rules |
| Wrong product claims | human quality gates declared | source-backed fact-checking and formal publisher approval |
| Brand or identity drift | blueprint locked against job overrides | visual continuity metrics and human review |
| Private customer data leaks | local processing by default | encryption, retention policy and per-job scoped credentials |
| Silent publication without QA | not_evaluated statuses preserved | fail-closed publication gateway and signed reviewers |

## Rights and origin

Every supplied asset declares its media kind, path, origin and rights. The origin may be filmed, licensed, owned, generated, screen-recorded or rendered. A generated asset is **not inherently free of third-party rights**. Source clips may contain protected music, logos, private details or real people's likenesses.

Clearance and evidence references are author-supplied assertions. The current compiler verifies their *presence*, not their authenticity. Do not store real releases, credentials, or private identifying information inside public template repositories. Maintain a private evidence store with identifiers and explicit publication scope.

For testimonials and documentary interviews, edits must not invert the speaker's meaning. Generated people and reconstructed events should be disclosed where applicable. Character/voice cloning needs appropriate permission and approval. Software demos should use current interfaces and must not invent working product behavior.

## Quality and publishing

An "automated" gate in a blueprint is **not** evidence of an executed evaluation. The v0.1 receipt reports such gates as not_evaluated. Job-listed human approvals are self_attested_approved, not cryptographically verified. A future release pipeline should require signature, reviewer role, scope, date, evidence hash, and explicit failure policy for every mandatory gate.

A reproducible production ledger should bind blueprint and engine version, original media hashes, generator model/request references, transformation graph, costs, caption variants, signed reviews and final artifact hashes.

The local reference renderer is appropriate for development and test fixtures. Do not expose it directly to anonymous uploads without additional operating-system isolation.
