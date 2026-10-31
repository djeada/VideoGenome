# Cockpits: CLI, Studio, agents and your own code

One engine, four ways to drive it. All of them share the same service layer
(`videogenome/service.py`), so a template filled in the Studio, by an agent
over MCP or from the command line goes through the same checks, pipeline,
gates and receipt.

| Who | Cockpit | Start it |
|---|---|---|
| People who want a video, not a terminal | **Studio**, a local web UI | `videogenome studio --pipeline procedural-writer --open` |
| Agents (Claude Code, Cursor, Agent SDK apps…) | **MCP server** | `videogenome mcp --pipeline procedural --workspace ~/vg-runs` |
| Power users and scripts | **CLI** | `videogenome --help` |
| Anyone with an animation already written | **Run code directly** | `videogenome capture page.html -o page.mp4` |

## The library: what is a prompt, what is code, what is ready

`videogenome library` lists every class of video (a *genome*) with a level
derived from what actually exists:

| Level | What you have | What you do |
|---|---|---|
| **TEMPLATE** | Ready-to-fill templates | Give a brief (or the slot values) and get a finished, gated video |
| **CODE** | Recipes: deterministic scenes, backgrounds, music | Choose a preset, tune bounded parameters, preview |
| **PROMPT** | An authoring prompt only | Hand it to an agent (`videogenome genome ID --prompt`, or the MCP prompt `author-ID`), let it write the code, preview it with `capture`, then promote it to a recipe and template |

Genomes live in `genomes/<id>/genome.json` with `prompt.md`; see
[scene authoring](scene-authoring.md) for how a class moves up the levels.

## Studio

[See the desktop and mobile interface previews](studio/README.md).

~~~bash
videogenome studio --pipeline procedural-writer --workspace ~/vg-runs --open
videogenome previews --pipeline procedural --workspace ~/vg-runs   # optional: library previews
~~~

* **Library**: every class as a card with its level, formats and what you must bring.
* **Make a video**: pick a template, then either write the copy in a form with
  live limits (characters, spoken words, VERBATIM tags) and press *Check*, or
  paste a brief and let the pipeline's writer fill it (*Write the copy*,
  *Brief to video*). Renders show the video, every gate and a link to the review page.
  Templates with several [delivery formats](delivery-formats.md) show a
  *Deliver in* picker (16:9, 9:16, 1:1...): one render makes each chosen format,
  and the result switches between them. *Check my copy* also lays the copy out
  in every chosen format.
* **Code**: tune any recipe's parameters (sliders, colour pickers, lists) and
  preview it in any format; paste or open your own HTML animation and render it
  unmodified, with its Web Audio recorded.
* **Runs**: everything rendered in the workspace.
* **Connect**: copy-paste commands for agents and the CLI.

The library supports text search, category and format filters, readiness tabs,
sorting, and saved styles. Card illustrations are labeled as illustrations;
rendered preview posters are labeled separately. Open **View details** to see
requirements and limits before choosing a template.

The editor starts with manual copy, works without a writing model, and offers
sample copy for a quick first render. **Start from a brief** uses the workspace's
configured writer when one is connected. Drafts are saved in this browser,
scoped to the workspace and template version; **Start fresh** clears the draft.
Copy checks mark the fields to revise, and failed requests keep the copy intact.
Render progress shows stages and elapsed time rather than invented percentages.

**My renders** can search, download, review, and reopen the original template
copy using **Edit copy**. Editing and rendering again leaves the original video
in its existing run. In **Motion lab**, selecting a look updates the visible
controls to that preset's values before rendering.

Security: the Studio binds to 127.0.0.1, prints a URL with a per-session token
(stored in an HttpOnly, SameSite=Strict cookie), refuses requests whose Host
header is not localhost (DNS rebinding), serves files from the workspace only,
and serves review pages with scripts disabled. The pipeline is fixed when
you start it; the UI cannot change providers, commands or endpoints.

Sample copy and preview jobs ship in installed wheels as well as source
checkouts. Video downloads stream from disk and support seeking with byte
ranges. Workspace HTML, HTM and SVG documents cannot run scripts or submit
forms when opened through the Studio.

## MCP server for agents

~~~bash
claude mcp add videogenome -- videogenome mcp --pipeline procedural --workspace ~/vg-runs
~~~

or, for other clients:

~~~json
{"mcpServers": {"videogenome": {"command": "videogenome",
  "args": ["mcp", "--pipeline", "procedural", "--workspace", "/home/me/vg-runs"]}}}
~~~

Tools: `library`, `genome`, `templates`, `template` (slot contracts, copy
examples, gates), `check_inputs`, `render`, `fill_from_brief` (only if the
pipeline has a writer), `recipes`, `preview_recipe`, `capture_html`, `runs`.
Prompts: `author-<genome>` for every class.

The intended loop has the agent acting as the writer:

1. `library` → choose a class; `template` → read each slot's limits and whether it is VERBATIM.
2. Write the copy, then `check_inputs` with the brief; fix every issue it returns.
   It also loads each code-rendered scene with the copy in every format the
   template offers and reports text that cannot fit, naming slot and format.
3. `render` → the video, the review page and the gate results, plus a contact
   sheet returned as an image so the agent can judge the result. Pass
   `formats: ["all"]` (or e.g. `["16x9", "9x16"]`) for one video per delivery
   format, each with its own gates and contact sheet.
4. For something no template covers, write a self-contained HTML animation and
   call `capture_html`; the page runs unmodified on the virtual clock.

No tool accepts a pipeline, provider, command, endpoint or a path outside the
workspace. The receipt and review page record that the copy came from an agent.

The server validates tool arguments against the schemas returned by
`tools/list`, including unknown keys and value types. Invalid requests return
JSON-RPC errors or tool errors while the session remains usable. Notifications
do not start renders. Recipe previews and HTML captures accept a `seed`;
frame rates must be integers from 1 to 120, durations from 0.05 to 600 seconds,
and output dimensions even numbers from 16 to 4096 pixels per side. Non-finite
numbers are rejected, including inside recipe parameters. `runs` accepts a
limit from 1 to 1000 and counts completed, readable run summaries.

## Run your own code directly

~~~bash
videogenome capture page.html -o page.mp4 --size 1080x1920 --fps 30 --duration 12
videogenome capture page.html -o page.mp4 --click            # click-to-play pages
videogenome capture page.html -o still.png --at 4.5          # one frame
~~~

The page runs **unmodified**. `requestAnimationFrame`, `performance.now`,
`Date`, timers and CSS/WAAPI animations follow a virtual clock that advances
exactly one frame per screenshot. `AudioContext` is rendered offline in
lockstep, so a page's own synth soundtrack lands on the right frames. The page
is served from a virtual origin, so ES modules, import maps and `fetch()` of
files beside it work, while every other request is blocked. Shared libraries
are available at `/_lib/vg-scene/vg-scene.js` and `/_lib/three/three.module.min.js`
(three.js 0.169 with addons under `/_lib/three/addons/`).

What does not carry over: `<video>`/`<audio>` element playback (use Web Audio
nodes), Workers with their own timers, and anything that needs the network.

To make a captured page reusable, run `videogenome recipe-new scene.name -o recipes/scene/name`
and move its copy, colours and timing into bounded parameters (see [scene authoring](scene-authoring.md)).
