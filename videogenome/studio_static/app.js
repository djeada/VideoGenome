"use strict";
// All copy, metadata and model replies enter the DOM as text, never HTML.
const $ = (selector) => document.querySelector(selector);
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(
      child instanceof Node ? child : document.createTextNode(String(child)),
    );
  }
  return el;
}
const clear = (el) => {
  el.replaceChildren();
  return el;
};
function icon(name) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("class", "icon");
  el.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(el.namespaceURI, "use");
  use.setAttribute("href", `#i-${name}`);
  el.append(use);
  return el;
}
const pretty = (text) =>
  String(text)
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
const FAMILY_NAMES = {
  typography: "Typography",
  data: "Data stories",
  explainer: "Explainers",
  brand: "Brand",
  product: "Product",
  social: "Social",
  "3d": "3D & cinematic",
  story: "Story & maps",
  maps: "Maps",
  generative: "Generative",
  music: "Music",
  code: "Code",
  documentary: "Documentary",
};
const LEVEL_LABEL = { template: "Template", code: "Recipe", prompt: "Concept" };
const VIEW_NAMES = {
  library: "Template library",
  make: "Video editor",
  code: "Motion lab",
  runs: "My renders",
  connect: "Connections",
};
const state = {
  info: null,
  library: [],
  templates: [],
  recipes: [],
  template: null,
  level: "",
  family: "",
  query: "",
  format: "",
  saved: new Set(),
  runs: [],
  busy: { make: false, code: false },
  loadSeq: 0,
  checkSeq: 0,
  mode: "manual",
  view: "library",
  loadingTemplate: false,
};
let checkTimer, draftTimer, toastTimer;
function readStorage(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}
function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
function toast(message, error = false) {
  const el = h("div", { class: `toast${error ? " error" : ""}` }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), error ? 7000 : 3500);
}
async function api(path, body) {
  let response;
  try {
    response = await fetch(
      `/api/${path}`,
      body === undefined
        ? { credentials: "same-origin" }
        : {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
    );
  } catch {
    throw new Error(
      "Studio could not be reached. Check that it is still running, then try again.",
    );
  }
  const data = await response
    .json()
    .catch(() => ({ error: "Studio returned an unreadable response." }));
  if (!response.ok)
    throw new Error(
      response.status === 403
        ? "Your Studio session has expired. Reopen the Studio link from your terminal."
        : data.error || response.statusText,
    );
  return data;
}
function closeNavigation() {
  $("#sidebar").classList.remove("open");
  $("#nav-toggle").setAttribute("aria-expanded", "false");
  $("#nav-backdrop").classList.add("hidden");
}
function show(view, updateHistory = true) {
  if (!VIEW_NAMES[view]) view = "library";
  state.view = view;
  document
    .querySelectorAll(".view")
    .forEach((el) => el.classList.toggle("active", el.id === `view-${view}`));
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === view);
    if (el.dataset.view === view) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  $("#page-title").textContent = VIEW_NAMES[view];
  document.title = `${VIEW_NAMES[view]} · VideoGenome Studio`;
  if (updateHistory) {
    const detail =
      view === "make" && state.template
        ? `/${encodeURIComponent(state.template.descriptor.id)}`
        : "";
    const hash = `#${view}${detail}`;
    if (location.hash !== hash) history.pushState(null, "", hash);
  }
  closeNavigation();
  if (view === "runs") loadRuns();
}
document
  .querySelectorAll("[data-view]")
  .forEach((el) => el.addEventListener("click", () => show(el.dataset.view)));
$("#nav-toggle").addEventListener("click", () => {
  const open = $("#sidebar").classList.toggle("open");
  $("#nav-toggle").setAttribute("aria-expanded", String(open));
  $("#nav-backdrop").classList.toggle("hidden", !open);
});
$("#nav-backdrop").addEventListener("click", closeNavigation);
$("#editor-back").addEventListener("click", () => show("library"));
$("#preview-toggle").addEventListener("click", () => {
  const collapsed = $("#make-output").classList.toggle("mobile-collapsed");
  $("#preview-toggle").textContent = collapsed
    ? "Show preview"
    : "Hide preview";
  $("#preview-toggle").setAttribute("aria-expanded", String(!collapsed));
});
$("#sidebar-explore").addEventListener("click", () => {
  show("library");
  $("#library-search").focus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeNavigation();
  if (
    e.key === "/" &&
    !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) &&
    !e.target.isContentEditable &&
    !$("#genome-dialog").open
  ) {
    e.preventDefault();
    show("library");
    $("#library-search").focus();
  }
});
window.addEventListener("hashchange", () => route());
function route() {
  const [view, id] = location.hash.slice(1).split("/");
  show(view || "library", false);
  if (
    view === "make" &&
    id &&
    decodeURIComponent(id) !== state.template?.descriptor.id
  )
    openTemplate(decodeURIComponent(id), false);
}
document
  .querySelectorAll("form")
  .forEach((form) =>
    form.addEventListener("submit", (e) => e.preventDefault()),
  );

// Original, code-native style illustrations. Real render posters take precedence.
function artKind(row) {
  const id = row.id || "";
  if (/chart/.test(id)) return "chart";
  if (/stat/.test(id)) return "data";
  if (/typing|code-snippet/.test(id) || row.family === "code") return "code";
  if (/cinematic|documentary|walkthrough|testimonial|reveal/.test(id))
    return "cinematic";
  if (/product|feature-launch|turntable/.test(id)) return "product";
  if (/quote/.test(id)) return "quote";
  if (/event/.test(id)) return "event";
  if (/route|map/.test(id)) return "route";
  if (/timeline|history/.test(id)) return "timeline";
  if (/music|beat|sound/.test(id) || row.family === "music") return "music";
  if (/how-it|steps|listicle|narrated|explainer/.test(id)) return "system";
  if (/backdrop|generative|zoom|physics|game|character/.test(id))
    return "abstract";
  return "typography";
}
function styleArt(row) {
  const kind = artKind(row);
  const texts = {
    typography: "Ideas.\nIn motion.",
    data: "42%",
    chart: "A story in every number.",
    product: "STUDIO",
    cinematic: "THE NEXT\nCHAPTER",
    quote: "One idea.\nWell told.",
    code: "const story = {\n  idea: 'something great',\n  action: 'make it happen'\n};",
    event: "03",
    system: "Big ideas. Simply explained.",
    music: "",
    route: "GO SOMEWHERE",
    abstract: "A little\npossibility.",
    timeline: "EVERY MOMENT MATTERS",
  };
  const art = h(
    "div",
    { class: `style-art art-${kind}`, "aria-hidden": "true" },
    h("span", { class: "art-copy" }, texts[kind]),
  );
  if (kind === "data")
    art.querySelector(".art-copy").append(h("small", {}, "MAKE IT COUNT"));
  if (kind === "chart")
    for (let i = 0; i < 4; i++) art.append(h("span", { class: "bar" }));
  if (kind === "system")
    for (let i = 0; i < 3; i++) art.append(h("span", { class: "node" }));
  if (kind === "music")
    for (let i = 0; i < 23; i++) art.append(h("span", { class: "wave" }));
  return art;
}
function rowForTemplate(id) {
  return (
    state.library.find((r) => (r.templates || []).includes(id)) || {
      id,
      family: "typography",
      title: id,
    }
  );
}
function filteredRows() {
  const q = state.query.trim().toLowerCase();
  const rows = state.library.filter(
    (r) =>
      (state.level === "saved"
        ? state.saved.has(r.id)
        : !state.level || state.level === r.level) &&
      (!state.family || state.family === r.family) &&
      (!state.format || r.formats.includes(state.format)) &&
      (!q ||
        [
          r.title,
          r.summary,
          r.family,
          ...(r.techniques || []),
          ...(r.templates || []),
          ...(r.recipes || []),
        ]
          .join(" ")
          .toLowerCase()
          .includes(q)),
  );
  const featured = [
    "kinetic-type",
    "stat-reveal",
    "product-hero-3d",
    "chart-story",
    "quote-loop",
    "cinematic-3d",
    "how-it-works",
    "event-countdown",
    "route-map",
  ];
  return rows.sort(
    $("#library-sort").value === "name"
      ? (a, b) => a.title.localeCompare(b.title)
      : (a, b) => {
          const score = (r) =>
            featured.includes(r.id)
              ? featured.indexOf(r.id)
              : r.level === "template"
                ? 20
                : r.level === "code"
                  ? 30
                  : 40;
          return score(a) - score(b) || a.title.localeCompare(b.title);
        },
  );
}
function updateCounts() {
  $("#nav-library-count").textContent = state.library.length;
  for (const el of document.querySelectorAll("[data-count]")) {
    const key = el.dataset.count;
    el.textContent =
      key === "all"
        ? state.library.length
        : key === "saved"
          ? state.saved.size
          : state.library.filter((r) => r.level === key).length;
  }
  $("#library-stats").textContent =
    `${state.library.filter((r) => r.level === "template").length} template styles. Endless stories.`;
}
function renderLibrary() {
  const grid = clear($("#library"));
  grid.setAttribute("aria-busy", "false");
  const rows = filteredRows();
  updateCounts();
  $("#results-count").textContent =
    `${rows.length} ${rows.length === 1 ? "style" : "styles"}`;
  if (!rows.length) {
    grid.append(
      emptyState(
        state.level === "saved" && !state.saved.size
          ? "Your inspiration, in one place"
          : "No styles match just yet",
        state.level === "saved" && !state.saved.size
          ? "Save a style with its bookmark button. Find it here whenever an idea strikes."
          : "Try another search or clear the filters to explore the full library.",
        "Explore all styles",
        resetFilters,
        "search",
      ),
    );
    return;
  }
  for (const row of rows) {
    const preview = Object.values(row.previews || {}).find((p) => p.poster);
    const thumb = h(
      "div",
      { class: "thumb" },
      preview
        ? h("img", {
            src: preview.poster,
            alt: `${row.title}: rendered sample`,
            loading: "lazy",
          })
        : styleArt(row),
      h("span", { class: `badge ${row.level}` }, LEVEL_LABEL[row.level]),
      h(
        "span",
        { class: "art-label" },
        preview ? "RENDERED SAMPLE" : "STYLE ILLUSTRATION",
      ),
      row.duration_seconds
        ? h(
            "span",
            { class: "duration-badge" },
            `${row.duration_seconds[0]}–${row.duration_seconds[1]}s`,
          )
        : null,
    );
    const save = h(
      "button",
      {
        class: "save-button",
        "aria-label": `${state.saved.has(row.id) ? "Unsave" : "Save"} ${row.title}`,
        "aria-pressed": String(state.saved.has(row.id)),
        onclick: () => {
          state.saved.has(row.id)
            ? state.saved.delete(row.id)
            : state.saved.add(row.id);
          writeStorage("vg-studio-saved", [...state.saved]);
          renderLibrary();
        },
      },
      icon("bookmark"),
    );
    const primary =
      row.level === "template"
        ? "Use template"
        : row.level === "code"
          ? "Open in lab"
          : "Explore concept";
    const open = () =>
      row.level === "template"
        ? openTemplate(row.templates[0])
        : row.level === "code"
          ? openRecipe(row.recipes[0])
          : openGenome(row.id);
    grid.append(
      h(
        "article",
        { class: "card tile", "data-genome": row.id },
        thumb,
        h(
          "div",
          { class: "body" },
          h("div", { class: "tile-title-row" }, h("h3", {}, row.title), save),
          h("p", {}, row.summary),
          h(
            "span",
            { class: "card-format" },
            `${FAMILY_NAMES[row.family] || pretty(row.family)} · ${row.formats.join(" / ")}`,
          ),
          h(
            "div",
            { class: "actions" },
            h(
              "button",
              { class: "text-button", onclick: () => openGenome(row.id) },
              "View details",
            ),
            h(
              "button",
              { class: "card-use", onclick: open },
              primary,
              icon("arrow"),
            ),
          ),
        ),
      ),
    );
  }
}
function resetFilters() {
  state.query = "";
  state.family = "";
  state.level = "";
  state.format = "";
  $("#library-search").value = "";
  $("#library-format").value = "";
  updateFilters();
  renderLibrary();
}
function updateFilters() {
  document.querySelectorAll("#level-filters button").forEach((b) => {
    const active = state.level === b.dataset.level;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("#family-filters button").forEach((b) => {
    const active = state.family === b.dataset.family;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", String(active));
  });
}
function buildFamilies() {
  const families = [...new Set(state.library.map((r) => r.family))].sort();
  clear($("#family-filters")).append(
    ...["", ...families].map((family) =>
      h(
        "button",
        {
          class: `family-button${!family ? " active" : ""}`,
          dataset: { family },
          "aria-pressed": String(!family),
          onclick: () => {
            state.family = family;
            updateFilters();
            renderLibrary();
          },
        },
        family ? FAMILY_NAMES[family] || pretty(family) : "Everything",
      ),
    ),
  );
}
$("#library-search").addEventListener("input", (e) => {
  state.query = e.target.value;
  renderLibrary();
});
$("#library-format").addEventListener("change", (e) => {
  state.format = e.target.value;
  renderLibrary();
});
$("#library-sort").addEventListener("change", renderLibrary);
document.querySelectorAll("#level-filters button").forEach((b) =>
  b.addEventListener("click", () => {
    state.level = b.dataset.level;
    updateFilters();
    renderLibrary();
  }),
);
$("#hero-start").addEventListener("click", () =>
  openTemplate("educational.title-card-sequence"),
);
$("#hero-featured").addEventListener("click", () => openGenome("kinetic-type"));
function emptyState(title, text, label, action, glyph = "film") {
  return h(
    "div",
    { class: "empty-state" },
    icon(glyph),
    h("h3", {}, title),
    h("p", {}, text),
    action ? h("button", { class: "btn", onclick: action }, label) : null,
  );
}
async function openGenome(id) {
  try {
    const g = await api(`genome/${encodeURIComponent(id)}`);
    const row = state.library.find((r) => r.id === id) || g;
    $("#genome-level").textContent =
      `${LEVEL_LABEL[g.level]} / ${FAMILY_NAMES[g.family] || pretty(g.family)}`;
    $("#genome-title").textContent = g.title;
    const body = clear($("#genome-body"));
    body.append(
      h("div", { class: "dialog-art" }, styleArt(row)),
      h("h3", { class: "dialog-title" }, g.title),
      h("p", { class: "dialog-description" }, g.summary),
      h(
        "div",
        { class: "template-facts" },
        h("span", {}, g.formats.join(" / ")),
        g.duration_seconds ? h("span", {}, `${g.duration_seconds.join("–")} seconds`) : null,
      ),
    );
    const actions = h("div", { class: "dialog-actions" });
    for (const template of g.templates || [])
      actions.append(
        h(
          "button",
          {
            class: "btn primary",
            onclick: () => {
              $("#genome-dialog").close();
              openTemplate(template);
            },
          },
          (g.templates || []).length === 1
            ? "Use this template"
            : pretty(template.split(".").pop()),
          icon("arrow"),
        ),
      );
    if (g.level === "code")
      for (const recipe of g.recipes || [])
        actions.append(
          h(
            "button",
            {
              class: "btn dark",
              onclick: () => {
                $("#genome-dialog").close();
                openRecipe(recipe);
              },
            },
            "Open recipe",
            icon("code"),
          ),
        );
    body.append(actions);
    for (const [title, lines] of [
      ["What you’ll bring", g.needs],
      ["Keep in mind", g.limits],
    ])
      if (lines?.length)
        body.append(
          h(
            "section",
            { class: "dialog-section" },
            h("h3", {}, title),
            h(
              "ul",
              {},
              lines.map((line) => h("li", {}, line)),
            ),
          ),
        );
    body.append(
      h(
        "details",
        { class: "dialog-section", open: g.level === "prompt" },
        h("summary", {}, "Build this style with an agent"),
        h(
          "p",
          { class: "hint" },
          "Copy this creative direction into your agent to build or extend the animation.",
        ),
        h("pre", { class: "prompt" }, g.prompt_text),
        copyButton(g.prompt_text, "Copy authoring prompt"),
      ),
    );
    $("#genome-dialog").showModal();
  } catch (e) {
    toast(e.message, true);
  }
}
$("#genome-close").addEventListener("click", () => $("#genome-dialog").close());
$("#genome-dialog").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) {
    const r = e.currentTarget.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      e.currentTarget.close();
  }
});

// Drafts are scoped to this browser, workspace, template and template version.
function draftKey(id) {
  return `vg-studio-draft:${state.info?.workspace || "local"}:${id}`;
}
function saveDraft() {
  if (!state.template || state.loadingTemplate) return;
  const ok = writeStorage(draftKey(state.template.descriptor.id), {
    version: state.template.descriptor.version,
    inputs: slotValues(),
    brief: $("#brief").value,
    mode: state.mode,
    updated: Date.now(),
  });
  $("#draft-status").textContent = ok
    ? "Draft saved in this browser"
    : "Draft could not be saved";
}
function changed() {
  state.checkSeq++;
  $("#draft-status").textContent = "Saving draft…";
  clearTimeout(draftTimer);
  draftTimer = setTimeout(saveDraft, 350);
  $("#check-summary").classList.add("hidden");
  clearTimeout(checkTimer);
  if (!state.busy.make && requiredComplete())
    checkTimer = setTimeout(() => checkCopy(false), 850);
  if ($("#step-render").classList.contains("active")) {
    $("#step-customize").className = "active";
    $("#step-render").className = "";
    $("#render-note").textContent =
      "Your preview shows the last render. Render again to see these edits.";
  }
}
window.addEventListener("pagehide", saveDraft);
function setMode(mode) {
  state.mode = mode;
  $("#brief-panel").classList.toggle("hidden", mode !== "brief");
  for (const key of ["manual", "brief"]) {
    $(`#mode-${key}`).classList.toggle("active", key === mode);
    $(`#mode-${key}`).setAttribute("aria-pressed", String(key === mode));
  }
}
$("#mode-manual").addEventListener("click", () => {
  setMode("manual");
  saveDraft();
});
$("#mode-brief").addEventListener("click", () => {
  setMode("brief");
  saveDraft();
  $("#brief").focus();
});
$("#brief").addEventListener("input", changed);
function updateActions() {
  const busy = state.busy.make || state.loadingTemplate || !state.template;
  for (const id of [
    "btn-render",
    "btn-check",
    "btn-sample",
    "btn-write",
    "btn-create",
    "template-select",
    "clear-draft",
  ])
    $("#" + id).disabled = busy;
  $("#btn-write").disabled = $("#btn-create").disabled =
    busy || !state.info?.writer || !state.template?.renders_from_text_alone;
  $("#btn-render").disabled = busy || !state.template?.renders_from_text_alone;
  $("#btn-sample").disabled =
    busy ||
    !(state.template?.sample_inputs || state.template?.copy_examples?.length);
  $("#btn-preview").disabled = $("#btn-capture").disabled = state.busy.code;
}
async function openTemplate(id, updateHistory = true) {
  if (state.busy.make && state.template?.descriptor.id !== id) {
    toast(
      "A render is running. You can choose another template when it finishes.",
    );
    return;
  }
  show("make", false);
  await loadTemplate(id);
  if (updateHistory && state.template?.descriptor.id === id) {
    const hash = `#make/${encodeURIComponent(id)}`;
    if (location.hash !== hash) history.pushState(null, "", hash);
  }
}
async function loadTemplate(id) {
  if (id === state.template?.descriptor.id) return;
  saveDraft();
  clearTimeout(checkTimer);
  state.checkSeq++;
  const seq = ++state.loadSeq;
  state.loadingTemplate = true;
  state.template = null;
  updateActions();
  $("#template-select").value = id;
  $("#template-info").replaceChildren(
    h("p", { class: "muted" }, "Loading your template…"),
  );
  clear($("#slots"));
  clear($("#make-deliverables"));
  $("#make-job").classList.add("hidden");
  $("#check-summary").classList.add("hidden");
  try {
    const t = await api(`template/${encodeURIComponent(id)}`);
    if (seq !== state.loadSeq) return;
    state.template = t;
    const d = t.descriptor;
    $("#step-customize").className = "active";
    $("#step-render").className = "";
    $("#template-select").value = d.id;
    const info = clear($("#template-info"));
    info.append(
      h("h2", {}, d.title),
      h("p", {}, d.description),
      h(
        "div",
        { class: "template-facts" },
        h("span", {}, `${d.output.aspect_ratio} format`),
        h("span", {}, `${d.duration_seconds}s runtime`),
        h("span", {}, `${d.output.width} × ${d.output.height}`),
      ),
    );
    if (!t.renders_from_text_alone)
      info.append(
        h(
          "div",
          { class: "notice warning" },
          "This style needs your own media. Use the CLI with your assets to render it. You can prepare and save its copy here.",
          h(
            "button",
            { class: "text-button", onclick: () => show("connect") },
            "See how",
          ),
        ),
      );
    $("#preview-title").textContent = d.title;
    $("#preview-format").textContent =
      `${d.output.aspect_ratio} · ${d.duration_seconds}s`;
    const player = clear($("#make-preview"));
    if (t.preview?.video) {
      player.classList.remove("empty");
      player.append(
        h("video", {
          src: t.preview.video,
          controls: true,
          muted: true,
          playsinline: true,
          poster: t.preview.poster || null,
        }),
      );
    } else {
      player.classList.add("empty");
      player.append(
        h("div", { class: "poster-holder" }, styleArt(rowForTemplate(id))),
        h(
          "div",
          { class: "empty-description" },
          "Style illustration · Your rendered video will appear here.",
        ),
      );
    }
    $("#preview-tip").classList.remove("hidden");
    if (t.sample_inputs && t.renders_from_text_alone && !t.preview?.video)
      info.append(
        h(
          "div",
          { class: "row" },
          h(
            "button",
            { class: "text-button", onclick: () => samplePreview(id) },
            "Render a sample to see this style ↗",
          ),
        ),
      );
    const stored = readStorage(draftKey(id), null);
    const draft =
      stored &&
      stored.version === d.version &&
      stored.inputs &&
      typeof stored.inputs === "object"
        ? stored
        : null;
    renderSlots(t.slots, draft?.inputs || {});
    $("#brief").value = typeof draft?.brief === "string" ? draft.brief : "";
    setMode(draft?.mode === "brief" ? "brief" : "manual");
    $("#draft-restored").classList.toggle("hidden", !draft);
    $("#draft-status").textContent = draft ? "Saved draft restored" : "";
    $("#render-note").textContent = t.renders_from_text_alone
      ? "Your original copy stays editable after rendering."
      : "Your copy is saved here. This template needs supplied media to render.";
  } catch (e) {
    if (seq === state.loadSeq)
      clear($("#template-info")).append(
        h(
          "div",
          { class: "notice bad", role: "alert" },
          e.message,
          h(
            "button",
            { class: "btn small", onclick: () => loadTemplate(id) },
            "Try again",
          ),
        ),
      );
  } finally {
    if (seq === state.loadSeq) {
      state.loadingTemplate = false;
      updateActions();
    }
  }
}
function renderSlots(slots, values) {
  const form = clear($("#slots"));
  for (const [name, c] of Object.entries(slots)) {
    const attrs = {
      name,
      id: `slot-${name}`,
      "aria-describedby": `hint-${name} count-${name} issue-${name}`,
      "aria-required": String(c.required),
    };
    let input;
    if (c.enum) {
      input = h(
        "select",
        attrs,
        c.required
          ? null
          : h(
              "option",
              { value: "" },
              c.default === undefined
                ? "Choose an option (optional)"
                : `Default: ${c.default}`,
            ),
        c.enum.map((v) => h("option", { value: JSON.stringify(v) }, String(v))),
      );
    } else if (c.type === "boolean")
      input = h("input", { ...attrs, type: "checkbox" });
    else if (c.type === "number")
      input = h("input", {
        ...attrs,
        type: "number",
        step: "any",
        placeholder: c.description,
      });
    else if (c.type === "string_array")
      input = h("textarea", {
        ...attrs,
        rows: 3,
        placeholder: "One idea per line",
      });
    else
      input =
        c.max_words ||
        c.max_chars > 90 ||
        (c.uses || []).some((u) => u.includes("typed"))
          ? h("textarea", { ...attrs, rows: 3, placeholder: c.description })
          : h("input", { ...attrs, type: "text", placeholder: c.description });
    const value = values[name] ?? c.default;
    if (value !== undefined) {
      if (c.type === "boolean") input.checked = Boolean(value);
      else
        input.value = c.enum
          ? JSON.stringify(value)
          : Array.isArray(value)
            ? value.join("\n")
            : String(value);
    }
    const count = h("span", { class: "count", id: `count-${name}` });
    const update = () => {
      const raw = input.value || "";
      const n =
        c.type === "string_array"
          ? Math.max(0, ...raw.split("\n").map((s) => s.length))
          : raw.length;
      const words = raw.trim() ? raw.trim().split(/\s+/).length : 0;
      count.textContent = c.max_words
        ? `${words} / ${c.max_words} words`
        : c.max_chars
          ? `${c.type === "string_array" ? "Longest line: " : ""}${n} / ${c.max_chars} characters`
          : "";
      count.classList.toggle(
        "over",
        Boolean(
          (c.max_words && words > c.max_words) ||
          (c.max_chars && n > c.max_chars),
        ),
      );
    };
    input.addEventListener("input", () => {
      input.dataset.touched = "1";
      update();
      changed();
    });
    input.addEventListener("change", () => {
      input.dataset.touched = "1";
      update();
      changed();
    });
    update();
    form.append(
      h(
        "div",
        { class: "field", dataset: { slot: name } },
        h(
          "label",
          { class: "slot-heading", for: `slot-${name}` },
          h(
            "span",
            {},
            pretty(name),
            c.mode === "verbatim"
              ? h(
                  "span",
                  {
                    class: "tag",
                    title: "Use the exact wording from your brief",
                  },
                  "EXACT WORDING",
                )
              : null,
          ),
          h(
            "span",
            { class: "slot-optional" },
            c.required ? "Required" : "Optional",
          ),
        ),
        h("span", { class: "hint", id: `hint-${name}` }, c.description),
        input,
        count,
        h("span", { class: "issue", id: `issue-${name}` }),
        c.uses?.length
          ? h(
              "details",
              { class: "slot-detail" },
              h("summary", {}, "Where this appears"),
              h("p", {}, c.uses.join("; ")),
            )
          : null,
      ),
    );
  }
}
function slotValues() {
  const values = {};
  if (!state.template) return values;
  for (const [name, c] of Object.entries(state.template.slots)) {
    const el = document.getElementById(`slot-${name}`);
    if (!el) continue;
    if (c.type === "boolean") {
      if (c.required || c.default !== undefined || el.dataset.touched)
        values[name] = el.checked;
      continue;
    }
    const raw = el.value;
    if (raw === "") continue;
    if (c.enum) {
      try {
        values[name] = JSON.parse(raw);
      } catch {
        values[name] = raw;
      }
    } else if (c.type === "number") values[name] = Number(raw);
    else if (c.type === "string_array")
      values[name] = raw
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
    else values[name] = raw;
  }
  return values;
}
function requiredComplete() {
  if (!state.template) return false;
  const values = slotValues();
  return Object.entries(state.template.slots).every(
    ([name, c]) =>
      !c.required ||
      (values[name] !== undefined &&
        values[name] !== "" &&
        (!Array.isArray(values[name]) || values[name].length)),
  );
}
function showIssues(result, focus = false) {
  document.querySelectorAll("#slots .field").forEach((f) => {
    f.classList.remove("bad");
    f.querySelector(".issue").textContent = "";
    f.querySelector("input,textarea,select").removeAttribute("aria-invalid");
  });
  for (const issue of result.issues || [])
    for (const slot of issue.slots || []) {
      const field = document.getElementById(`slot-${slot}`)?.closest(".field");
      if (field) {
        field.classList.add("bad");
        field.querySelector(".issue").textContent = issue.problem;
        field
          .querySelector("input,textarea,select")
          .setAttribute("aria-invalid", "true");
      }
    }
  const summary = clear($("#check-summary"));
  summary.className = `notice ${result.ok ? "good" : "bad"}`;
  summary.append(
    result.ok
      ? "Your copy fits. You’re ready to render."
      : `${result.issues.length} ${result.issues.length === 1 ? "thing" : "things"} to adjust. Check the highlighted fields.`,
  );
  if (result.ok && result.verbatim_unverified?.length)
    summary.append(
      h(
        "div",
        { class: "hint" },
        "Names, numbers, and quotes still need your review. Add the source brief to check exact wording.",
      ),
    );
  for (const issue of result.issues || [])
    if (!issue.slots?.length) summary.append(h("div", {}, issue.problem));
  if (focus && !result.ok) $("#slots [aria-invalid=true]")?.focus();
}
async function checkCopy(explicit = true) {
  if (!state.template || state.loadingTemplate) return null;
  const seq = ++state.checkSeq,
    id = state.template.descriptor.id,
    inputs = slotValues(),
    snapshot = JSON.stringify(inputs);
  try {
    const result = await api("check", {
      template: id,
      inputs,
      brief: $("#brief").value.trim() || null,
    });
    if (
      seq !== state.checkSeq ||
      id !== state.template?.descriptor.id ||
      snapshot !== JSON.stringify(slotValues())
    )
      return null;
    showIssues(result, explicit);
    return result;
  } catch (e) {
    if (explicit) showError($("#make-job"), e);
    return null;
  }
}
$("#btn-check").addEventListener("click", async () => {
  if (state.busy.make) return;
  $("#btn-check").disabled = true;
  await checkCopy(true);
  updateActions();
});
$("#btn-sample").addEventListener("click", () => {
  const t = state.template;
  if (!t) return;
  const example = t.copy_examples?.[0];
  renderSlots(t.slots, example?.inputs || t.sample_inputs || {});
  $("#brief").value = example?.brief || "";
  $("#check-summary").classList.add("hidden");
  saveDraft();
  toast("Sample copy added. Make it your own.");
});
$("#clear-draft").addEventListener("click", () => {
  if (!state.template) return;
  clearTimeout(draftTimer);
  clearTimeout(checkTimer);
  state.checkSeq++;
  try {
    localStorage.removeItem(draftKey(state.template.descriptor.id));
  } catch {}
  renderSlots(state.template.slots, {});
  $("#brief").value = "";
  $("#draft-restored").classList.add("hidden");
  $("#draft-status").textContent = "Fresh start";
  $("#check-summary").classList.add("hidden");
});

// Rendering has indeterminate progress, explicit recovery, and one active operation per editor.
function showError(panel, error, retry) {
  panel.classList.remove("hidden");
  clear(panel).append(
    h(
      "div",
      { class: "notice bad", role: "alert" },
      error.message || String(error),
    ),
    retry
      ? h(
          "button",
          { class: "btn small job-retry", onclick: retry },
          "Try again",
        )
      : null,
  );
}
async function follow(jobId, panel) {
  panel.classList.remove("hidden");
  const title = h("b", {}, "Getting things ready"),
    elapsed = h("span", { class: "muted" });
  const track = h("div", { class: "job-track" }, h("span"));
  const log = h("pre");
  const started = Date.now();
  clear(panel).append(
    h(
      "div",
      { class: "job-heading" },
      h("div", { class: "job-stage" }, h("span", { class: "spinner" }), title),
      elapsed,
    ),
    track,
    h("details", {}, h("summary", {}, "Show render details"), log),
  );
  for (;;) {
    const job = await api(`jobs/${jobId}`);
    const lines = job.log || [];
    const last = lines.join(" ").toLowerCase();
    title.textContent =
      job.status === "queued"
        ? "Waiting for an available renderer"
        : /rendering/.test(last)
          ? "Rendering your video"
          : /produc/.test(last)
            ? "Creating your media"
            : /copy|write/.test(job.label)
              ? "Drafting your copy"
              : "Bringing your idea to life";
    elapsed.textContent = `${Math.floor((Date.now() - started) / 1000)}s elapsed`;
    log.textContent = lines.join("\n");
    if (job.status === "done") {
      title.textContent = "Complete";
      track.classList.add("done");
      panel.querySelector(".spinner")?.remove();
      return job.result;
    }
    if (job.status === "failed")
      throw new Error(
        job.error || "The render could not finish. Your copy has been kept.",
      );
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}
function gateSummary(result) {
  const statuses = Object.values(result.gates || {}),
    failed = statuses.filter((s) => s === "failed").length,
    passed = statuses.filter((s) => s === "passed").length;
  return failed
    ? `${failed} ${failed === 1 ? "check needs" : "checks need"} attention`
    : passed
      ? `${passed} ${passed === 1 ? "technical check passed" : "technical checks passed"}`
      : "Ready for review";
}
function resultView(result, player, panel) {
  clear(player).classList.remove("empty");
  const url = result.output_url || "";
  if (/\.mp4(?:$|\?)/i.test(url))
    player.append(
      h("video", {
        src: url,
        controls: true,
        muted: true,
        playsinline: true,
        poster: result.poster_url || null,
      }),
    );
  else if (/\.(png|jpg)(?:$|\?)/i.test(url))
    player.append(h("img", { src: url, alt: "Your rendered image" }));
  else if (/\.wav(?:$|\?)/i.test(url)) {
    player.classList.add("empty");
    player.append(icon("play"), h("audio", { src: url, controls: true }));
  }
  const target = $(
    panel.id.startsWith("make") ? "#make-deliverables" : "#code-deliverables",
  );
  clear(target).append(
    h(
      "div",
      { class: "result-heading" },
      icon("check"),
      "Your render is ready",
    ),
  );
  if (result.gates)
    target.append(
      h(
        "div",
        { class: "gates" },
        Object.entries(result.gates).map(([id, status]) =>
          h(
            "span",
            {
              class: `gate ${status}`,
              title: `${pretty(id)}: ${status.replaceAll("_", " ")}`,
            },
            pretty(id),
            " · ",
            status === "not_evaluated"
              ? "Review needed"
              : status.replaceAll("_", " "),
          ),
        ),
      ),
    );
  if (result.contains_placeholder_media)
    target.append(
      h(
        "div",
        { class: "notice warning" },
        "This render includes stand-in media. Review the receipt before sharing.",
      ),
    );
  target.append(
    h(
      "div",
      { class: "links" },
      result.output_url
        ? h(
            "a",
            {
              class: "btn primary small",
              href: result.output_url,
              download: "",
            },
            icon("download"),
            "Download",
          )
        : null,
      result.review_page_url
        ? h(
            "a",
            { href: result.review_page_url, target: "_blank", rel: "noopener" },
            "Review video ↗",
          )
        : null,
      result.contact_sheet_url
        ? h(
            "a",
            {
              href: result.contact_sheet_url,
              target: "_blank",
              rel: "noopener",
            },
            "Contact sheet",
          )
        : null,
      result.receipt_url
        ? h(
            "a",
            { href: result.receipt_url, target: "_blank", rel: "noopener" },
            "Receipt",
          )
        : null,
    ),
  );
  target.append(
    h(
      "p",
      { class: "result-note" },
      "A successful render still needs your creative and factual review.",
    ),
  );
  if (panel.id === "make-job") {
    $("#make-output").classList.remove("mobile-collapsed");
    $("#preview-toggle").textContent = "Hide preview";
    $("#preview-toggle").setAttribute("aria-expanded", "true");
    $("#preview-tip").classList.add("hidden");
    $("#step-customize").classList.remove("active");
    $("#step-customize").classList.add("done");
    $("#step-render").classList.add("active");
  }
}
async function runOperation(zone, work) {
  if (state.busy[zone]) return;
  state.busy[zone] = true;
  if (zone === "make") {
    clearTimeout(checkTimer);
    state.checkSeq++;
  }
  updateActions();
  const panel = $(`#${zone}-job`);
  clear($(zone === "make" ? "#make-deliverables" : "#code-deliverables"));
  try {
    await work(panel);
  } catch (e) {
    showError(panel, e, () => runOperation(zone, work));
  } finally {
    state.busy[zone] = false;
    updateActions();
  }
}
$("#btn-render").addEventListener("click", () =>
  runOperation("make", async (panel) => {
    const checked = await checkCopy(true);
    if (!checked?.ok) return;
    saveDraft();
    const { job } = await api("render", {
      template: state.template.descriptor.id,
      inputs: slotValues(),
      brief: $("#brief").value.trim() || null,
    });
    resultView(await follow(job, panel), $("#make-preview"), panel);
  }),
);
$("#btn-write").addEventListener("click", () =>
  runOperation("make", async (panel) => {
    const brief = $("#brief").value.trim();
    if (!brief) {
      $("#brief").focus();
      throw new Error(
        "Tell us what your video is about first. Include the facts and wording to use.",
      );
    }
    const { job } = await api("fill", {
      template: state.template.descriptor.id,
      brief,
    });
    const r = await follow(job, panel);
    renderSlots(state.template.slots, r.inputs);
    saveDraft();
    panel.append(
      h(
        "div",
        { class: `notice ${r.status === "complete" ? "good" : "warning"}` },
        r.status === "complete"
          ? "Your copy is drafted. Give it a read, then render when you’re happy."
          : r.status === "incomplete"
            ? "Add these facts to the brief: " +
              (r.missing || [])
                .map((m) => `${pretty(m.input)} (${m.reason})`)
                .join("; ")
            : "A little more editing is needed: " +
              (r.issues || []).map((i) => i.problem).join("; "),
      ),
    );
  }),
);
$("#btn-create").addEventListener("click", () =>
  runOperation("make", async (panel) => {
    const brief = $("#brief").value.trim();
    if (!brief) {
      $("#brief").focus();
      throw new Error("Add a brief before creating your video.");
    }
    saveDraft();
    const { job } = await api("create", {
      template: state.template.descriptor.id,
      brief,
    });
    resultView(await follow(job, panel), $("#make-preview"), panel);
  }),
);
async function samplePreview(id) {
  return runOperation("make", async (panel) => {
    const { job } = await api(`preview-template/${encodeURIComponent(id)}`, {});
    resultView(await follow(job, panel), $("#make-preview"), panel);
    await refreshLibrary();
  });
}

// Recipes display the chosen preset's actual values, not unrelated defaults.
function fillRecipeSelect() {
  const select = clear($("#recipe-select"));
  const order = (r) =>
    r.id.startsWith("scene.") ? 0 : r.id.startsWith("visual.") ? 1 : 2;
  select.append(
    ...[...state.recipes]
      .sort((a, b) => order(a) - order(b) || a.title.localeCompare(b.title))
      .map((r) => h("option", { value: r.id }, r.title)),
  );
  select.onchange = () => loadRecipe(select.value);
  if (state.recipes.length) loadRecipe(select.value);
}
function openRecipe(id) {
  show("code");
  $("#recipe-select").value = id;
  loadRecipe(id);
}
function loadRecipe(id) {
  const recipe = state.recipes.find((r) => r.id === id);
  if (!recipe) return;
  $("#recipe-info").textContent = recipe.description;
  clear($("#recipe-preset")).append(
    h("option", { value: "" }, "Original look"),
    ...recipe.presets.map((p) => h("option", { value: p }, pretty(p))),
  );
  $("#recipe-size").disabled =
    recipe.media.length === 1 && recipe.media[0] === "audio";
  const renderParams = () => {
    const overrides = recipe.preset_values?.[$("#recipe-preset").value] || {};
    clear($("#recipe-params")).append(
      ...Object.entries(recipe.params_schema.properties).map(([name, schema]) =>
        paramField(name, {
          ...schema,
          default: overrides[name] ?? schema.default,
        }),
      ),
    );
  };
  $("#recipe-preset").onchange = renderParams;
  renderParams();
}
function paramField(name, schema) {
  const wrap = h(
    "div",
    { class: "field", dataset: { param: name } },
    h("label", { for: `param-${name}`, class: "slot-heading" }, pretty(name)),
    h(
      "span",
      { class: "hint", id: `param-hint-${name}` },
      schema.description || "",
    ),
  );
  let input;
  const def = schema.default;
  const attrs = {
    id: `param-${name}`,
    "aria-describedby": `param-hint-${name}`,
    dataset: { changed: "" },
  };
  if (schema.enum) {
    input = h(
      "select",
      attrs,
      schema.enum.map((v) =>
        h("option", { value: JSON.stringify(v) }, String(v)),
      ),
    );
    input.value = JSON.stringify(def);
  } else if (schema.type === "boolean") {
    input = h("input", { ...attrs, type: "checkbox" });
    input.checked = Boolean(def);
  } else if (
    ["number", "integer"].includes(schema.type) &&
    schema.minimum !== undefined &&
    schema.maximum !== undefined
  ) {
    const out = h(
      "span",
      { class: "hint", "aria-live": "polite" },
      String(def),
    );
    input = h("input", {
      ...attrs,
      type: "range",
      min: schema.minimum,
      max: schema.maximum,
      step:
        schema.type === "integer" ? 1 : (schema.maximum - schema.minimum) / 100,
    });
    input.value = def;
    input.addEventListener("input", () => {
      out.textContent = input.value;
    });
    wrap.append(out);
  } else if (
    schema.type === "array" &&
    schema.items?.pattern?.includes("0-9A-Fa-f")
  ) {
    input = h(
      "div",
      { ...attrs, class: "colors" },
      (def || []).map((color, i) =>
        h("input", {
          type: "color",
          value: color,
          "aria-label": `${pretty(name)} color ${i + 1}`,
        }),
      ),
    );
    input.dataset.kind = "colors";
  } else if (schema.type === "array") {
    input = h("textarea", {
      ...attrs,
      rows: 3,
      placeholder:
        schema.items?.type === "string"
          ? "One item per line"
          : "One JSON value per line",
    });
    input.dataset.kind = "lines";
    input.value = (def || [])
      .map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v)))
      .join("\n");
  } else {
    input = h("input", {
      ...attrs,
      type: ["number", "integer"].includes(schema.type) ? "number" : "text",
    });
    input.value =
      def === undefined
        ? ""
        : typeof def === "object"
          ? JSON.stringify(def)
          : String(def);
  }
  input.addEventListener("input", () => {
    input.dataset.changed = "1";
  });
  input.addEventListener("change", () => {
    input.dataset.changed = "1";
  });
  wrap.append(input);
  return wrap;
}
function recipeParams() {
  const recipe = state.recipes.find((r) => r.id === $("#recipe-select").value),
    params = {};
  document.querySelectorAll("#recipe-params .field").forEach((field) => {
    const name = field.dataset.param,
      schema = recipe.params_schema.properties[name],
      input = field.querySelector("[data-changed]");
    if (!input || input.dataset.changed !== "1") return;
    if (input.dataset.kind === "colors")
      params[name] = [...input.querySelectorAll("input")].map((el) =>
        el.value.toUpperCase(),
      );
    else if (schema.enum) params[name] = JSON.parse(input.value);
    else if (schema.type === "boolean") params[name] = input.checked;
    else if (["number", "integer"].includes(schema.type))
      params[name] = Number(input.value);
    else if (input.dataset.kind === "lines")
      params[name] = input.value
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          if (schema.items?.type === "string") return line;
          try {
            return JSON.parse(line);
          } catch {
            throw new Error(
              `${pretty(name)} needs one valid JSON value on each line.`,
            );
          }
        });
    else params[name] = input.value;
  });
  return params;
}
$("#btn-preview").addEventListener("click", () =>
  runOperation("code", async (panel) => {
    const { job } = await api("preview-recipe", {
      recipe: $("#recipe-select").value,
      preset: $("#recipe-preset").value,
      params: recipeParams(),
      size: $("#recipe-size").value,
      duration: Number($("#recipe-duration").value),
    });
    resultView(await follow(job, panel), $("#code-preview"), panel);
  }),
);
$("#html-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (file.size > 3 * 1024 * 1024)
      throw new Error("Choose an HTML file smaller than 3 MB.");
    $("#html").value = await file.text();
    toast(`${file.name} is ready to render.`);
  } catch (error) {
    toast(error.message, true);
  }
});
$("#btn-capture").addEventListener("click", () =>
  runOperation("code", async (panel) => {
    const html = $("#html").value;
    if (!html.trim()) {
      $("#html").focus();
      throw new Error("Paste your HTML animation or choose a file first.");
    }
    const { job } = await api("capture", {
      html,
      size: $("#html-size").value,
      duration: Number($("#html-duration").value),
      click: $("#html-click").checked,
      audio: $("#html-audio").checked,
    });
    resultView(await follow(job, panel), $("#code-preview"), panel);
  }),
);

// Saved renders remain useful: search, inspect, download, and reopen their copy.
async function loadRuns() {
  clear($("#runs")).append(
    h("div", { class: "loading-card" }, "Finding your renders…"),
  );
  try {
    state.runs = await api("runs");
    renderRuns();
  } catch (e) {
    clear($("#runs")).append(
      emptyState(
        "Your renders could not be loaded",
        e.message,
        "Try again",
        loadRuns,
      ),
    );
  }
}
function renderRuns() {
  const grid = clear($("#runs")),
    q = $("#runs-search").value.trim().toLowerCase();
  const rows = state.runs.filter((r) =>
    [r.template, r.recipe, r.run, r.kind].join(" ").toLowerCase().includes(q),
  );
  if (!rows.length) {
    grid.append(
      emptyState(
        state.runs.length
          ? "No renders match that search"
          : "Your ideas belong here",
        state.runs.length
          ? "Try another name to find your work."
          : "Make your first video and it will be waiting here. Ready to edit, review, and share.",
        state.runs.length ? "Clear search" : "Make a video",
        state.runs.length
          ? () => {
              $("#runs-search").value = "";
              renderRuns();
            }
          : () => openTemplate("educational.title-card-sequence"),
      ),
    );
    return;
  }
  for (const r of rows) {
    const row = r.template
      ? rowForTemplate(r.template)
      : { id: r.recipe || r.kind, family: "generative" };
    const thumb = h(
      "div",
      { class: "thumb" },
      r.poster_url
        ? h("img", {
            src: r.poster_url,
            alt: `Rendered ${row.title || r.kind}`,
            loading: "lazy",
          })
        : r.contact_sheet_url
          ? h("img", {
              src: r.contact_sheet_url,
              alt: "Render contact sheet",
              loading: "lazy",
            })
          : styleArt(row),
    );
    const failed = (r.automated_gates_failed || []).length;
    grid.append(
      h(
        "article",
        { class: "card tile run-tile" },
        thumb,
        h(
          "div",
          { class: "body" },
          h("h3", {}, row.title || r.recipe || "Custom animation"),
          h(
            "div",
            { class: "meta" },
            new Date(r.created).toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            }),
            r.duration_seconds ? ` · ${r.duration_seconds}s` : "",
          ),
          h(
            "span",
            { class: `run-status${failed ? " failed" : ""}` },
            gateSummary(r),
          ),
          h(
            "div",
            { class: "links" },
            r.template
              ? h(
                  "button",
                  { class: "btn small", onclick: () => editRun(r.run) },
                  "Edit copy",
                )
              : null,
            r.output_url
              ? h(
                  "a",
                  { class: "btn small", href: r.output_url, download: "" },
                  icon("download"),
                  "Download",
                )
              : null,
            r.review_page_url
              ? h(
                  "a",
                  {
                    href: r.review_page_url,
                    target: "_blank",
                    rel: "noopener",
                  },
                  "Review ↗",
                )
              : r.output_url
                ? h(
                    "a",
                    { href: r.output_url, target: "_blank", rel: "noopener" },
                    "Open ↗",
                  )
                : null,
          ),
        ),
      ),
    );
  }
}
async function editRun(name) {
  try {
    const run = await api(`run/${encodeURIComponent(name)}`);
    if (state.busy.make) {
      toast("Finish the current render before opening another edit.");
      return;
    }
    await openTemplate(run.template);
    if (!state.template || state.template.descriptor.id !== run.template)
      return;
    renderSlots(state.template.slots, run.inputs);
    $("#brief").value = run.brief || "";
    saveDraft();
    toast("Copy restored. Your original render is kept.");
  } catch (e) {
    toast(e.message, true);
  }
}
$("#runs-search").addEventListener("input", renderRuns);
$("#refresh-runs").addEventListener("click", loadRuns);
function copyButton(text, label = "Copy") {
  const button = h(
    "button",
    {
      class: "btn small",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = "Copied ✓";
          setTimeout(() => {
            button.textContent = label;
          }, 2000);
        } catch {
          toast(
            "Copy is unavailable here. Select the text and copy it manually.",
            true,
          );
        }
      },
    },
    label,
  );
  return button;
}
function renderConnect() {
  const s = state.info,
    quote = (value) => "'" + String(value).replaceAll("'", "'\\''") + "'";
  const mcp = `videogenome mcp --pipeline ${quote(s.pipeline)} --workspace ${quote(s.workspace)}`;
  const config = JSON.stringify(
    {
      mcpServers: {
        videogenome: {
          command: "videogenome",
          args: ["mcp", "--pipeline", s.pipeline, "--workspace", s.workspace],
        },
      },
    },
    null,
    2,
  );
  const command = (text, label = "Copy command") =>
    h("div", {}, h("pre", { class: "cmd" }, text), copyButton(text, label));
  clear($("#connect")).append(
    h(
      "section",
      { class: "card" },
      h("h2", {}, "Create with your agent"),
      h(
        "p",
        {},
        "Give your agent the same templates, copy checks, and video renders as Studio.",
      ),
      h("p", { class: "hint" }, "Claude Code"),
      command(`claude mcp add videogenome -- ${mcp}`),
      h("p", { class: "hint" }, "Other MCP clients"),
      command(config, "Copy configuration"),
    ),
    h(
      "section",
      { class: "card" },
      h("h2", {}, "Make it scriptable"),
      h(
        "p",
        {},
        "Go from a brief to a video, or render a job from your own workflow.",
      ),
      command(
        `videogenome library\nvideogenome create social.kinetic-promo \\\n  --pipeline procedural-writer \\\n  --brief-file brief.txt -o promo.mp4\nvideogenome make job.json --pipeline ${quote(s.pipeline)} -o video.mp4`,
      ),
      h(
        "p",
        { class: "hint" },
        "Templates needing your media use a job file with local assets and rights information.",
      ),
    ),
    h(
      "section",
      { class: "card" },
      h("h2", {}, "Bring your animation"),
      h(
        "p",
        {},
        "A self-contained HTML scene, captured with exact frame timing and synchronized Web Audio.",
      ),
      command(
        "videogenome capture page.html -o video.mp4 \\\n  --size 1080x1920 --duration 12\nvideogenome recipe-new scene.my-scene \\\n  -o recipes/scene/my-scene",
      ),
      h(
        "button",
        { class: "text-button", onclick: () => show("code") },
        "Open motion lab ↗",
      ),
    ),
  );
}
async function refreshLibrary() {
  state.library = await api("library");
  buildFamilies();
  renderLibrary();
}
async function boot() {
  try {
    state.info = await api("state");
    [state.templates, state.recipes, state.library] = await Promise.all([
      api("templates"),
      api("recipes"),
      api("library"),
    ]);
    const stored = readStorage("vg-studio-saved", []);
    state.saved = new Set(
      (Array.isArray(stored) ? stored : []).filter((id) =>
        state.library.some((r) => r.id === id),
      ),
    );
    $("#studio-version").textContent = `v${state.info.version}`;
    $("#workspace-status").textContent = "Ready to create";
    clear($("#state")).append(
      h(
        "span",
        { class: "chip" },
        "Pipeline ",
        h("b", {}, state.info.pipeline),
      ),
      h(
        "span",
        { class: "chip" },
        "Writing model ",
        h("b", {}, state.info.writer || "Not connected"),
      ),
    );
    $("#writer-note").textContent = state.info.writer
      ? "Drafts use your connected writing model. Review its copy before sharing."
      : "No writing model is connected to this workspace. You can use sample copy and write your own, or connect a model through your pipeline.";
    const select = clear($("#template-select"));
    const groups = {};
    for (const t of state.templates) (groups[t.category] ||= []).push(t);
    for (const [category, rows] of Object.entries(groups).sort())
      select.append(
        h(
          "optgroup",
          { label: pretty(category) },
          rows.map((t) =>
            h("option", { value: t.id }, `${t.title} · ${t.aspect_ratio}`),
          ),
        ),
      );
    select.onchange = () => openTemplate(select.value);
    buildFamilies();
    renderLibrary();
    fillRecipeSelect();
    renderConnect();
    updateActions();
    $("#app-error").classList.add("hidden");
    const [view, requested] = location.hash.slice(1).split("/");
    const initial =
      requested && view === "make"
        ? decodeURIComponent(requested)
        : "educational.title-card-sequence";
    await loadTemplate(
      state.templates.some((t) => t.id === initial)
        ? initial
        : state.templates[0]?.id,
    );
    show(VIEW_NAMES[view] ? view : "library", false);
  } catch (e) {
    $("#workspace-status").textContent = "Connection needs attention";
    const panel = clear($("#app-error"));
    panel.classList.remove("hidden");
    panel.append(
      e.message,
      " ",
      h("button", { class: "btn small", onclick: boot }, "Reconnect"),
    );
  }
}
boot();
