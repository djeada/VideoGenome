"use strict";
// VideoGenome Studio front end. Data is always inserted with textContent (h()), never as HTML.

const $ = (sel) => document.querySelector(sel);
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(`/api/${path}`, { credentials: "same-origin", ...options });
  const data = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

const state = { info: null, library: [], templates: [], recipes: [], template: null, levelFilter: "" };

// ---- navigation -------------------------------------------------------------------
function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  if (view === "runs") loadRuns();
  history.replaceState(null, "", `#${view}`);
}
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.view)));

// ---- jobs -----------------------------------------------------------------------------
async function follow(jobId, panel, onDone) {
  panel.classList.remove("hidden");
  const status = h("div", {}, h("span", { class: "status queued" }, "queued"));
  const log = h("pre");
  clear(panel).append(status, log);
  for (;;) {
    const job = await api(`jobs/${jobId}`);
    clear(status).append(h("span", { class: `status ${job.status}` }, job.status), " ", h("span", { class: "muted" }, job.label));
    log.textContent = job.log.join("\n");
    log.scrollTop = log.scrollHeight;
    if (job.status === "done") { onDone && onDone(job.result); return job.result; }
    if (job.status === "failed") { status.append(h("div", { class: "notice bad" }, job.error)); return null; }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

function resultView(result, player, panel) {
  clear(player).classList.remove("empty");
  if (result.output_url && result.output_url.endsWith(".mp4")) {
    player.append(h("video", { src: result.output_url, controls: true, autoplay: true, muted: true, loop: true,
                               playsinline: true, poster: result.poster_url || null }));
  } else if (result.output_url && /\.(png|jpg)$/.test(result.output_url)) {
    player.append(h("img", { src: result.output_url, alt: "Preview still" }));
  } else if (result.output_url && result.output_url.endsWith(".wav")) {
    player.classList.add("empty"); player.append(h("audio", { src: result.output_url, controls: true }));
  }
  const extra = h("div");
  if (result.gates) {
    extra.append(h("div", { class: "gates" }, Object.entries(result.gates).map(([id, s]) =>
      h("span", { class: `gate ${s}`, title: s }, `${id}: ${s.replace(/_/g, " ")}`))));
  }
  if (result.contains_placeholder_media) extra.append(h("div", { class: "notice bad" }, "Contains placeholder media: an animatic, not for publication."));
  if (result.audio) extra.append(h("div", { class: "meta" }, `Audio: ${result.audio}`));
  extra.append(h("div", { class: "links" },
    result.output_url && h("a", { href: result.output_url, download: "" }, "Download"),
    result.review_page_url && h("a", { href: result.review_page_url, target: "_blank", rel: "noopener" }, "Review page"),
    result.contact_sheet_url && h("a", { href: result.contact_sheet_url, target: "_blank", rel: "noopener" }, "Contact sheet"),
    result.receipt_url && h("a", { href: result.receipt_url, target: "_blank", rel: "noopener" }, "Receipt")));
  panel.append(extra);
}

// ---- library ------------------------------------------------------------------------------
const LEVEL_LABEL = { template: "Template", code: "Code", prompt: "Prompt" };
function renderLibrary() {
  const grid = clear($("#library"));
  const rows = state.library.filter((r) => !state.levelFilter || r.level === state.levelFilter);
  for (const row of rows) {
    const preview = Object.values(row.previews || {}).find((p) => p.poster || p.video);
    const thumb = h("div", { class: "thumb" },
      preview && preview.poster ? h("img", { src: preview.poster, alt: "", loading: "lazy" })
                                : h("span", { class: "glyph" }, row.family),
      h("span", { class: `badge ${row.level}` }, LEVEL_LABEL[row.level]));
    const actions = h("div", { class: "actions" });
    for (const id of row.templates || []) {
      actions.append(h("button", { class: "btn small primary", onclick: () => openTemplate(id) }, `Make: ${id.split(".").pop()}`));
    }
    if (row.level === "code") {
      for (const id of row.recipes || []) actions.append(h("button", { class: "btn small", onclick: () => openRecipe(id) }, id));
    }
    actions.append(h("button", { class: "btn small ghost", onclick: () => openGenome(row.id) },
      row.level === "prompt" ? "Get the prompt" : "Details"));
    grid.append(h("article", { class: "card tile" }, thumb, h("div", { class: "body" },
      h("h3", {}, row.title), h("p", {}, row.summary),
      h("div", { class: "meta" }, `${row.family} · ${row.formats.join(" / ")}${row.needs && row.needs.length ? " · needs " + row.needs.join(", ") : ""}`),
      actions)));
  }
  if (!rows.length) grid.append(h("p", { class: "muted" }, "Nothing at this level yet."));
}
document.querySelectorAll("#level-filters .chip-btn").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#level-filters .chip-btn").forEach((x) => x.classList.toggle("active", x === b));
  state.levelFilter = b.dataset.level; renderLibrary();
}));

async function openGenome(id) {
  const g = await api(`genome/${encodeURIComponent(id)}`);
  $("#genome-title").textContent = `${g.title}  ·  ${LEVEL_LABEL[g.level]}`;
  const body = clear($("#genome-body"));
  body.append(h("p", {}, g.summary));
  if (g.templates && g.templates.length) body.append(h("p", {}, h("b", {}, "Templates: "), g.templates.join(", ")));
  if (g.recipes && g.recipes.length) body.append(h("p", {}, h("b", {}, "Code: "), g.recipes.join(", ")));
  if (g.needs && g.needs.length) body.append(h("p", {}, h("b", {}, "You bring: "), g.needs.join("; ")));
  if (g.limits && g.limits.length) body.append(h("ul", { class: "plain" }, g.limits.map((l) => h("li", {}, l))));
  body.append(h("div", { class: "row spread" }, h("h2", {}, "Authoring prompt"),
    h("button", { class: "btn small", onclick: () => navigator.clipboard.writeText(g.prompt_text) }, "Copy")));
  body.append(h("p", { class: "muted small" }, "Give this to your agent (or use the MCP prompt author-" + g.id +
    ") to build new code in this class; preview it under Code, Run your own code."));
  body.append(h("pre", { class: "prompt" }, g.prompt_text));
  $("#genome-dialog").showModal();
}
$("#genome-close").addEventListener("click", () => $("#genome-dialog").close());

// ---- make ---------------------------------------------------------------------------------
function fillTemplateSelect() {
  const select = clear($("#template-select"));
  const groups = {};
  for (const t of state.templates) (groups[t.category] = groups[t.category] || []).push(t);
  for (const [category, items] of Object.entries(groups).sort()) {
    select.append(h("optgroup", { label: category }, items.map((t) =>
      h("option", { value: t.id }, `${t.title} (${t.aspect_ratio}, ${t.duration_seconds}s)`))));
  }
  select.addEventListener("change", () => loadTemplate(select.value));
}

async function openTemplate(id) {
  show("make");
  $("#template-select").value = id;
  await loadTemplate(id);
}

async function loadTemplate(id) {
  const t = await api(`template/${encodeURIComponent(id)}`);
  state.template = t;
  const d = t.descriptor;
  const info = clear($("#template-info"));
  info.append(h("h2", {}, d.title), h("p", { class: "small" }, d.description),
    h("div", { class: "meta" }, `${d.output.aspect_ratio} · ${d.duration_seconds}s · ${d.output.width}×${d.output.height}`),
    !t.renders_from_text_alone ? h("div", { class: "notice bad" },
      "This template needs media you supply (" + Object.entries(t.media_inputs).filter(([, m]) => m.required && !m.producible)
        .map(([n]) => n).join(", ") + "); the Studio renders text-driven templates.") : null,
    h("div", { class: "row" },
      t.preview && t.preview.video ? null : h("button", { class: "btn small ghost", disabled: !t.sample_inputs,
        onclick: () => samplePreview(id) }, "Render a sample preview")));
  if (t.preview && t.preview.video) {
    const player = clear($("#make-preview")); player.classList.remove("empty");
    player.append(h("video", { src: t.preview.video, controls: true, muted: true, loop: true, autoplay: true, playsinline: true }));
  } else {
    clear($("#make-preview")).classList.add("empty");
    $("#make-preview").textContent = "Your video appears here.";
  }
  $("#btn-sample").disabled = !t.sample_inputs;
  renderSlots(t.slots, {});
  $("#check-summary").classList.add("hidden");
}

function renderSlots(slots, values) {
  const form = clear($("#slots"));
  for (const [name, c] of Object.entries(slots)) {
    let input;
    if (c.enum) {
      input = h("select", { name }, c.required ? null : h("option", { value: "" }, `(default${c.default !== undefined ? ": " + c.default : ""})`),
        c.enum.map((v) => h("option", { value: v }, String(v))));
    } else if (c.type === "number") {
      input = h("input", { name, type: "number", step: "any" });
    } else if (c.type === "string_array") {
      input = h("textarea", { name, rows: 3, placeholder: "One per line" });
    } else {
      const long = (c.max_chars && c.max_chars > 90) || c.max_words || (c.uses || []).some((u) => u.includes("typed"));
      input = long ? h("textarea", { name, rows: (c.uses || []).some((u) => u.includes("typed")) ? 7 : 3 })
                   : h("input", { name, type: "text" });
    }
    const value = values[name];
    if (value !== undefined) input.value = Array.isArray(value) ? value.join("\n") : String(value);
    const count = h("span", { class: "count" });
    const update = () => {
      if (!c.max_chars && !c.max_words) return;
      const v = input.value || "";
      const words = v.trim() ? v.trim().split(/\s+/).length : 0;
      const over = (c.max_chars && v.length > c.max_chars) || (c.max_words && words > c.max_words);
      count.textContent = c.max_words ? `${words} / ${c.max_words} words` : `${v.length} / ${c.max_chars}`;
      count.classList.toggle("over", Boolean(over));
    };
    input.addEventListener("input", update); update();
    form.append(h("label", { class: "field", dataset: { slot: name } },
      h("span", {}, name, c.required ? "" : " (optional)", c.mode === "verbatim" ? h("span", { class: "tag", title: "Must be copied exactly from the brief" }, "VERBATIM") : null),
      h("span", { class: "hint" }, c.description),
      (c.uses || []).length ? h("span", { class: "hint" }, "Used as: " + c.uses.join("; ")) : null,
      input, count, h("span", { class: "issue" })));
  }
}

function slotValues() {
  const values = {};
  for (const [name, c] of Object.entries(state.template.slots)) {
    const el = document.querySelector(`#slots [name="${CSS.escape(name)}"]`);
    if (!el) continue;
    const raw = el.value;
    if (raw === "" || raw === undefined) continue;
    if (c.type === "number") values[name] = Number(raw);
    else if (c.type === "string_array") values[name] = raw.split("\n").map((s) => s.trim()).filter(Boolean);
    else if (c.enum && typeof c.enum[0] === "number") values[name] = Number(raw);
    else values[name] = raw;
  }
  return values;
}

function showIssues(result) {
  document.querySelectorAll("#slots .field").forEach((f) => { f.classList.remove("bad"); f.querySelector(".issue").textContent = ""; });
  const summary = $("#check-summary");
  summary.classList.remove("hidden", "good", "bad");
  const general = [];
  for (const issue of result.issues) {
    const field = issue.slots.length ? document.querySelector(`#slots .field[data-slot="${CSS.escape(issue.slots[0])}"]`) : null;
    if (field) { field.classList.add("bad"); field.querySelector(".issue").textContent = issue.problem; }
    else general.push(issue.problem);
  }
  summary.classList.add(result.ok ? "good" : "bad");
  summary.textContent = result.ok ? "Everything fits the template." + (result.note ? " " + result.note : "")
    : `${result.issues.length} problem(s) to fix.` + (general.length ? " " + general.join(" ") : "");
}

$("#btn-sample").addEventListener("click", () => renderSlots(state.template.slots, state.template.sample_inputs || {}));
$("#btn-check").addEventListener("click", async () => {
  const brief = $("#brief").value.trim();
  showIssues(await api("check", { template: state.template.descriptor.id, inputs: slotValues(), brief: brief || null }));
});
$("#btn-render").addEventListener("click", async () => {
  const brief = $("#brief").value.trim();
  const check = await api("check", { template: state.template.descriptor.id, inputs: slotValues(), brief: brief || null });
  showIssues(check);
  if (!check.ok) return;
  const { job } = await api("render", { template: state.template.descriptor.id, inputs: slotValues(), brief: brief || null });
  follow(job, $("#make-job"), (r) => resultView(r, $("#make-preview"), $("#make-job")));
});
$("#btn-write").addEventListener("click", async () => {
  const brief = $("#brief").value.trim();
  if (!brief) return;
  const { job } = await api("fill", { template: state.template.descriptor.id, brief });
  const result = await follow(job, $("#make-job"));
  if (!result) return;
  renderSlots(state.template.slots, result.inputs);
  const panel = $("#make-job");
  panel.append(h("div", { class: `notice ${result.status === "complete" ? "good" : "bad"}` },
    result.status === "complete" ? `Copy written in ${result.attempts} attempt(s). Review it, then Render.`
      : result.status === "incomplete" ? "The brief lacks facts these slots need: " + result.missing.map((m) => `${m.input} (${m.reason})`).join("; ")
      : "The writer could not fit the template: " + result.issues.map((i) => i.problem).join("; ")));
});
$("#btn-create").addEventListener("click", async () => {
  const brief = $("#brief").value.trim();
  if (!brief) return;
  const { job } = await api("create", { template: state.template.descriptor.id, brief });
  follow(job, $("#make-job"), (r) => resultView(r, $("#make-preview"), $("#make-job")));
});
async function samplePreview(id) {
  const { job } = await api(`preview-template/${encodeURIComponent(id)}`, {});
  follow(job, $("#make-job"), (r) => { resultView(r, $("#make-preview"), $("#make-job")); refreshLibrary(); });
}

// ---- code -----------------------------------------------------------------------------------
function fillRecipeSelect() {
  const select = clear($("#recipe-select"));
  const order = (r) => (r.id.startsWith("scene.") ? 0 : r.id.startsWith("visual.") ? 1 : 2);
  for (const r of [...state.recipes].sort((a, b) => order(a) - order(b) || a.id.localeCompare(b.id))) {
    select.append(h("option", { value: r.id }, `${r.id} · ${r.title}`));
  }
  select.addEventListener("change", () => loadRecipe(select.value));
  if (state.recipes.length) loadRecipe(select.value);
}
function openRecipe(id) { show("code"); $("#recipe-select").value = id; loadRecipe(id); }

function loadRecipe(id) {
  const r = state.recipes.find((x) => x.id === id);
  if (!r) return;
  clear($("#recipe-info")).append(r.description);
  const preset = clear($("#recipe-preset"));
  preset.append(h("option", { value: "" }, "(defaults)"), r.presets.map((p) => h("option", { value: p }, p)));
  $("#recipe-size").disabled = r.media.length === 1 && r.media[0] === "audio";
  const form = clear($("#recipe-params"));
  for (const [name, schema] of Object.entries(r.params_schema.properties)) {
    form.append(paramField(name, schema));
  }
}

function paramField(name, schema) {
  const wrap = h("label", { class: "field", dataset: { param: name } }, h("span", {}, name), h("span", { class: "hint" }, schema.description || ""));
  let input;
  const def = schema.default;
  if (schema.enum) {
    input = h("select", {}, schema.enum.map((v) => h("option", { value: JSON.stringify(v) }, String(v))));
    input.value = JSON.stringify(def);
  } else if (schema.type === "boolean") {
    input = h("input", { type: "checkbox" }); input.checked = Boolean(def);
  } else if ((schema.type === "number" || schema.type === "integer") && schema.minimum !== undefined && schema.maximum !== undefined) {
    const out = h("span", { class: "hint" }, String(def));
    input = h("input", { type: "range", min: schema.minimum, max: schema.maximum,
                         step: schema.type === "integer" ? 1 : (schema.maximum - schema.minimum) / 100 });
    input.value = def; input.addEventListener("input", () => { out.textContent = input.value; });
    wrap.append(out);
  } else if (schema.type === "array" && schema.items && schema.items.pattern && schema.items.pattern.includes("0-9A-Fa-f")) {
    input = h("div", { class: "colors" }, (def || []).map((c) => h("input", { type: "color", value: c })));
    input.dataset.kind = "colors";
  } else if (schema.type === "array") {
    input = h("textarea", { rows: 3, placeholder: "One item per line" });
    input.value = (def || []).map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join("\n");
    input.dataset.kind = "lines";
  } else {
    input = h("input", { type: schema.type === "number" || schema.type === "integer" ? "number" : "text" });
    input.value = def === undefined ? "" : (typeof def === "object" ? JSON.stringify(def) : String(def));
  }
  input.dataset.changed = "";
  input.addEventListener("input", () => { input.dataset.changed = "1"; });
  input.addEventListener("change", () => { input.dataset.changed = "1"; });
  wrap.append(input);
  return wrap;
}

function recipeParams() {
  const r = state.recipes.find((x) => x.id === $("#recipe-select").value);
  const params = {};
  document.querySelectorAll("#recipe-params .field").forEach((field) => {
    const name = field.dataset.param, schema = r.params_schema.properties[name];
    const input = field.querySelector("[data-changed]");
    const colors = field.querySelector(".colors");
    if (colors) {
      const values = [...colors.querySelectorAll("input")].map((i) => i.value.toUpperCase());
      if (JSON.stringify(values) !== JSON.stringify((schema.default || []).map((c) => c.toUpperCase()))) params[name] = values;
      return;
    }
    if (!input || input.dataset.changed !== "1") return;
    if (schema.enum) params[name] = JSON.parse(input.value);
    else if (schema.type === "boolean") params[name] = input.checked;
    else if (schema.type === "number") params[name] = Number(input.value);
    else if (schema.type === "integer") params[name] = Math.round(Number(input.value));
    else if (input.dataset.kind === "lines") {
      const lines = input.value.split("\n").map((s) => s.trim()).filter(Boolean);
      params[name] = schema.items && schema.items.type && schema.items.type !== "string"
        ? lines.map((l) => { try { return JSON.parse(l); } catch { return l; } }) : lines;
    } else params[name] = input.value;
  });
  return params;
}

$("#btn-preview").addEventListener("click", async () => {
  const body = { recipe: $("#recipe-select").value, preset: $("#recipe-preset").value, params: recipeParams(),
                 size: $("#recipe-size").value, duration: Number($("#recipe-duration").value) };
  try {
    const { job } = await api("preview-recipe", body);
    follow(job, $("#code-job"), (r) => resultView(r, $("#code-preview"), $("#code-job")));
  } catch (e) { clear($("#code-job")).classList.remove("hidden"); $("#code-job").append(h("div", { class: "notice bad" }, e.message)); }
});
$("#html-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (file) $("#html").value = await file.text();
});
$("#btn-capture").addEventListener("click", async () => {
  const html = $("#html").value;
  if (!html.trim()) return;
  const { job } = await api("capture", { html, size: $("#html-size").value, duration: Number($("#html-duration").value),
                                         click: $("#html-click").checked, audio: $("#html-audio").checked });
  follow(job, $("#code-job"), (r) => resultView(r, $("#code-preview"), $("#code-job")));
});

// ---- runs -------------------------------------------------------------------------------------
async function loadRuns() {
  const grid = clear($("#runs"));
  const runs = await api("runs");
  if (!runs.length) { grid.append(h("p", { class: "muted" }, "No runs yet.")); return; }
  for (const r of runs) {
    const thumb = h("div", { class: "thumb" },
      r.output_url && r.output_url.endsWith(".mp4") ? h("video", { src: r.output_url, muted: true, preload: "metadata", controls: true })
        : r.contact_sheet_url ? h("img", { src: r.contact_sheet_url, alt: "" }) : h("span", { class: "glyph" }, r.kind));
    const failed = (r.automated_gates_failed || []).length;
    grid.append(h("article", { class: "card tile" }, thumb, h("div", { class: "body" },
      h("h3", {}, r.template || r.recipe || r.page || r.run),
      h("div", { class: "meta" }, `${r.kind} · ${new Date(r.created).toLocaleString()}`),
      r.gates ? h("div", { class: "meta" }, failed ? `${failed} automated gate(s) failed` : "automated gates passed") : null,
      h("div", { class: "links" },
        r.output_url && h("a", { href: r.output_url, download: "" }, "Download"),
        r.review_page_url && h("a", { href: r.review_page_url, target: "_blank", rel: "noopener" }, "Review"),
        r.contact_sheet_url && h("a", { href: r.contact_sheet_url, target: "_blank", rel: "noopener" }, "Sheet")))));
  }
}

// ---- connect --------------------------------------------------------------------------------
function renderConnect() {
  const s = state.info;
  const mcp = `videogenome mcp --pipeline ${s.pipeline} --workspace ${s.workspace}`;
  const config = JSON.stringify({ mcpServers: { videogenome: { command: "videogenome",
    args: ["mcp", "--pipeline", s.pipeline, "--workspace", s.workspace] } } }, null, 2);
  const cmd = (text) => h("div", {}, h("pre", { class: "cmd" }, text),
    h("button", { class: "btn small", onclick: () => navigator.clipboard.writeText(text) }, "Copy"));
  clear($("#connect")).append(
    h("div", { class: "card" }, h("h2", {}, "Connect your agent (MCP)"),
      h("p", { class: "small" }, "Your agent browses the library, reads slot contracts, writes the copy itself, checks it with the same validator, renders with this pipeline, and sees a contact sheet of the result. It can also send HTML it wrote and get a frame-exact video back."),
      h("p", { class: "small muted" }, "Claude Code:"), cmd(`claude mcp add videogenome -- ${mcp}`),
      h("p", { class: "small muted" }, "Other MCP clients (JSON config):"), cmd(config)),
    h("div", { class: "card" }, h("h2", {}, "Power users: CLI"),
      h("p", { class: "small" }, "Everything here, scriptable and composable."),
      cmd("videogenome library\nvideogenome create social.kinetic-promo --pipeline procedural-writer -o out/promo.mp4 \\\n  --brief \"...\"\nvideogenome fill TEMPLATE --brief-file brief.txt -o job.json\nvideogenome make job.json --pipeline procedural -o out/video.mp4\nvideogenome bench examples/briefs/smoke.json --pipeline procedural-writer")),
    h("div", { class: "card" }, h("h2", {}, "Run code directly"),
      h("p", { class: "small" }, "Any self-contained HTML animation renders unmodified and frame-exactly; Web Audio is recorded in sync. Promote a good one to a recipe."),
      cmd("videogenome capture page.html -o page.mp4 --size 1080x1920 --duration 12 --click\nvideogenome recipe-new scene.my-scene -o recipes/scene/my-scene [--three]\nvideogenome genome kinetic-type --prompt   # authoring prompt for your agent")));
}

// ---- boot ---------------------------------------------------------------------------------------
async function refreshLibrary() { state.library = await api("library"); renderLibrary(); }
async function boot() {
  state.info = await api("state");
  clear($("#state")).append(
    h("span", { class: "chip" }, "pipeline ", h("b", {}, state.info.pipeline)),
    h("span", { class: "chip" }, "writer ", h("b", {}, state.info.writer || "none")),
    h("span", { class: "chip" }, `v${state.info.version}`));
  $("#btn-write").disabled = $("#btn-create").disabled = !state.info.writer;
  $("#writer-note").textContent = state.info.writer ? `Writer: ${state.info.writer}`
    : "No writer in this pipeline: write the copy below, or start the Studio with a profile that has one.";
  [state.templates, state.recipes] = await Promise.all([api("templates"), api("recipes")]);
  await refreshLibrary();
  fillTemplateSelect(); fillRecipeSelect(); renderConnect();
  const first = state.templates.find((t) => t.id === "social.kinetic-promo") || state.templates[0];
  if (first) { $("#template-select").value = first.id; loadTemplate(first.id); }
  const view = location.hash.replace("#", "");
  if (["library", "make", "code", "runs", "connect"].includes(view)) show(view);
}
boot().catch((e) => document.body.prepend(h("div", { class: "notice bad" }, `Studio failed to start: ${e.message}`)));
