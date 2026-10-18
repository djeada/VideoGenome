# Briefs and writers: from a plain-language brief to a valid job

A template locks the craft: story structure, timing, typography, motion,
sound and quality gates. What remains is the copy: a hook, three tips, a
product name, a narration line. `videogenome fill` gives that last step to a
**writer**, any chat model the operator configures, and checks every word
the writer proposes before it reaches a job.

~~~bash
videogenome fill social.kinetic-promo --pipeline procedural-writer -o job.json \
  --brief "Promo for Harbourline, a ferry app: buy tickets in ten seconds, see live departures, board by scanning your phone."
videogenome create social.kinetic-promo --pipeline procedural-writer -o out/harbourline.mp4 \
  --brief-file brief.txt          # fill + produce + render + gates + review page
videogenome bench examples/briefs/smoke.json --pipeline procedural-writer -o bench.json
~~~

## Who decides what

| Decision | Made by |
|---|---|
| Story, timing, layout, motion, palette, sound, gates | Template author (locked in the blueprint) |
| Which writer model, endpoint, temperature | Operator (pipeline profile `writer`) |
| Copy for text slots, choices among enums | Writer, within the slot contracts |
| Whether copy fits, reads in time, is speakable in its slot | Compiler and renderer (measured) |
| Whether a quote, name or testimonial is real | The brief: verbatim slots must match it |
| Media, rights, approvals | Never the writer |

## Slot contracts

`fill` derives each text slot's contract from the blueprint, so the writer
sees the same limits the compiler will enforce:

* **On-screen copy**: title cards (estimated characters at the locked size,
  then measured with the pinned font), captions (line and reading-speed
  limits), and scene recipe text params (their `maxLength`).
* **Narration**: words budgeted from the locked slot length at 2.5 words per
  second. Produced speech is measured afterwards; if it still runs long,
  `create` sends the measured length back to the writer, which shortens
  exactly the copy that feeds that voice.
* **Prompts and search queries**: described as concrete visible things,
  because a pipeline may search CC0 libraries or prompt a generator with them.
* **Enums**: the writer may only choose listed values.

The writer's reply is untrusted JSON. Unknown keys are dropped, types and
enums are checked, emoji the locked font cannot draw are refused, and every
problem is sent back with the exact value it concerns. After the attempt
budget (default 3) the job is written only if every check passes.

## Verbatim slots and honest refusals

Schema 0.5.0 lets an input declare a `fill` policy:

| `fill` | Meaning |
|---|---|
| `write` (default for text) | The writer composes it from the brief |
| `verbatim` | It must be words copied exactly from the brief: names, quotes, testimonials, approved calls to action |
| `never` (default for `url`) | Only a person supplies it |

For verbatim slots the filler extracts candidate phrases from the brief
(quoted text, `Label: value` pairs, proper-name runs) and offers them to the
writer. Any proposal that does not appear in the brief is rejected. If the
writer cannot ground a verbatim slot, **the system** marks it missing. A model
that invents a testimonial produces an incomplete job, never a fabricated one.

A brief that lacks required facts ends with status `incomplete` (exit code 4).
The draft job and a list of what is missing are written, and nothing is produced.

## Copy examples: how the expert teaches the writer

A blueprint may carry up to three `copy_examples`: a brief and the ideal
values, with a note on why they work. They are shown to the writer as a
worked example ("copy its specificity, tone and length, never its content"),
and `python -m tools.validate` runs them through the same checks as a
writer's reply, so an example can never teach copy that breaks the template.

~~~json
"copy_examples": [{
  "brief": "Reel for home cooks who keep burning garlic. Three fixes: ...",
  "inputs": {"hook": "Stop burning your garlic", "tip_1": "Add garlic after the onions soften, never at the start.", "...": "..."},
  "note": "The hook names the viewer's problem in a few words. Each tip keeps the concrete detail from the brief."
}]
~~~

## Writers

| Type | Talks to | Notes |
|---|---|---|
| `openai-chat` | `POST {base_url}/chat/completions` | Ollama, llama.cpp server, vLLM, LM Studio, LocalAI, hosted APIs. Uses `response_format: json_schema` (constrained decoding where supported); `structured_output: json_object` or `none` for servers without it. `api_key_env` names an environment variable; keys never live in profiles. |
| `command` | Any CLI, prompt on stdin, JSON on stdout | `llm`, `claude -p`, a llama.cpp binary, a script. `argv` takes no placeholders: briefs never reach a command line. `stdin: messages` sends `{system, messages, schema}` as JSON instead of a flattened transcript. |

Third-party writers register under the `videogenome.writers` entry-point
group and implement `Writer.write(system, messages, schema) -> Written`.

A profile adds a writer next to its providers:

~~~json
{"pipeline_schema": "0.1.0", "id": "procedural-writer", "extends": "procedural",
 "description": "...", "verification": "...",
 "writer": {"type": "openai-chat", "config": {
   "base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen2.5:3b", "temperature": 0.4,
   "model": {"name": "Qwen2.5-3B-Instruct", "license": "Qwen Research License"}}}}
~~~

## Records

`fill` writes `<job>.fill.json` beside the job. It records the brief and its
hash, the writer and model, the template hash, every attempt (problems found,
reply hash, timing, token counts) and which inputs were written, pinned or
missing. `render`, `make` and `create` carry that record into the receipt and
the review page (`<output>.review.html`), so a reviewer sees that the copy
came from a model and which brief it answered.

## Benchmarking a writer

`videogenome bench SUITE.json` runs a suite of briefs, each with an expected
outcome (`complete`, or `incomplete` for briefs that lack required facts), and
reports:

* `fill_rate` and `first_attempt_rate`: valid jobs, and how many needed no feedback;
* `mean_attempts` and `median_writer_seconds`;
* `honest_refusal_rate`: briefs without the facts that ended `incomplete`
  instead of being filled with invented ones;
* with `--render DIR`, whether every rendered video passed its automated gates.

`examples/briefs/smoke.json` holds twelve briefs across the text-fillable
templates. It includes two that lack required facts and one that tries to
override the rules. On 2026-10-18 the `procedural-writer` profile
(Qwen2.5-3B-Instruct on Ollama 0.30.8, RTX 5060) met every expectation in
two consecutive runs: fill rate 1.0, first-attempt rate 0.9, honest refusals
1.0, about one second per brief.

**Bench measures validity and honesty, not quality.** In those runs a 3B
writer still produced flat lines, dropped a detail from a code example, and
in one case added a mild claim the brief did not make ("sorting donations
efficiently increases capacity"). Templates keep their human review gates
(`claims_review`, `accuracy_review`, `brand_review`) for exactly this.

### Class suites (2026-10-18, Qwen2.5-3B on Ollama, `procedural-writer`)

| Suite | As expected | Fill rate | Honest refusals | Misses |
|---|---|---|---|---|
| smoke (12 templates) | 12/12 | 1.0 | 1.0 | — |
| chart-story | 4/4 | 1.0 | 1.0 | — |
| history-timeline | 4/4 | 1.0 | 1.0 | — |
| quote-loop | 4/4 | 1.0 | 1.0 | — |
| beat-visualizer | 4/4 | 1.0 | 1.0 | — |
| motion-showreel | 4/4 | 1.0 | 1.0 | — |
| stat-reveal | 4/5 | 0.67 | 1.0 | one complete brief ended incomplete |
| event-countdown | 4/5 | 1.0 | 0.5 | a brief with no day count reused a number from the date |
| feature-launch | 3/4 | 0.67 | 1.0 | one brief failed after three attempts |
| route-map | 3/4 | 0.67 | 1.0 | one brief ended incomplete |
| how-it-works | 3/4 | 1.0 | 0.0 | a vague brief got an invented system (node labels are written, not verbatim) |
| code-snippet | 3/5 | 0.75 | 0.0 | invented the client's code; Rust brief failed |

52 of 59 briefs met expectations. The pattern: verbatim slots (names, quotes,
numbers next to their labels) hold up well even with a 3B model; slots the
writer composes cannot be checked against the brief, so human review gates
remain essential for code, diagrams and claims.
