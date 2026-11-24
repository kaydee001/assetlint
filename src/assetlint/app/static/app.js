// Asset Lint app: fetches results from the local server and shows them.
// All logic lives in Python; this file only displays and sends requests.
// Three places, one per rail item: Overview (health and what to do next), Problems (every
// problem, grouped by check, with why and how to fix), and Rules (rules.js).
"use strict";

const token = (() => {
  const fromUrl = new URLSearchParams(location.search).get("token");
  if (fromUrl) sessionStorage.setItem("assetlint-token", fromUrl);
  return fromUrl || sessionStorage.getItem("assetlint-token") || "";
})();

const $ = (id) => document.getElementById(id);
const state = {
  data: null,          // the last check's result
  info: { checks: [], recent: [], can_browse: false },
  view: "overview",
  severities: new Set(["error", "warn"]),
  rule: null,          // show only this check's problems
  fixableOnly: false,  // show only files with a one-click fix
  query: "",
  before: null,        // problems before the last check of the same folder
};
const VIEWS = ["overview", "problems", "rules"];

// --- server ---------------------------------------------------------------

async function api(path, body) {
  const options = { headers: { "X-Assetlint-Token": token } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `The app answered ${response.status}.`);
  return data;
}

// --- small helpers -----------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) node.append(child);
  }
  return node;
}

// Drawn icons, one 16px grid and one stroke weight. `label` makes it announced; else it's decorative.
const ICONS = {
  close: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
  error: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5.25v3.25M8 10.75v.01"/>',
  warn: '<path d="M8 2.75l5.75 10H2.25z"/><path d="M8 6.75v2.5M8 11.25v.01"/>',
  ok: '<circle cx="8" cy="8" r="5.5"/><path d="M5.5 8.2l1.7 1.7 3.3-3.6"/>',
  wand: '<path d="M3 13l7-7M9 3.5V2M12.5 7H14M11.5 4.5l1-1M5.5 3l.5 1.5M12 10.5l1.5.5"/>',
  arrow: '<path d="M3.5 8h9M9 4.5L12.5 8 9 11.5"/>',
  cube: '<path class="cube-edge" d="M8 1.75l5.4 3.1v6.3L8 14.25l-5.4-3.1v-6.3z"/>' +
        '<path class="cube-inner" d="M2.6 4.85L8 8l5.4-3.15M8 8v6.25"/>',
};

function icon(name, label = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", `icon icon-${name}`);
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
  } else {
    svg.setAttribute("aria-hidden", "true");
  }
  svg.innerHTML = ICONS[name]; // fixed strings above, never user data
  return svg;
}

// "D:\game\assets\assetlint.toml" -> "assets/assetlint.toml" (the full path is in the tooltip)
function shortConfigPath(path) {
  return path.split(/[\\/]/).filter(Boolean).slice(-2).join("/");
}

function folderName(path) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function plural(n, word, many = `${word}s`) {
  return `${n.toLocaleString()} ${n === 1 ? word : many}`;
}

// Sizes as file managers show them: 1,500,000 -> "1.5 MB".
function size(bytes) {
  for (const [unit, scale] of [["GB", 1e9], ["MB", 1e6], ["KB", 1e3]]) {
    if (bytes >= scale) return `${(bytes / scale).toFixed(1).replace(/\.0$/, "")} ${unit}`;
  }
  return `${bytes} B`;
}

function splitPath(path) {
  const slash = path.lastIndexOf("/");
  return [slash >= 0 ? path.slice(0, slash + 1) : "", path.slice(slash + 1)];
}

function pathLabel(path) {
  const [dir, name] = splitPath(path);
  return el("span", { class: "path", title: path }, el("span", { class: "dir" }, dir), el("span", { class: "name" }, name));
}

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (box.hidden = true), 4000);
}

// Every screen opens the same way: what it is, in one line, and its main action.
function pageHeader(title, purpose, ...actions) {
  return el("header", { class: "page-head" },
    el("div", {}, el("h1", {}, title), el("p", {}, purpose)),
    actions.length ? el("div", { class: "page-actions" }, actions) : null);
}

function card(props, ...children) {
  return el("section", { ...props, class: `card ${props.class || ""}` }, children);
}

function cardTitle(text, note) {
  return el("h2", { class: "card-title" }, text, note ? el("span", { class: "note" }, note) : null);
}

function chooseFolder() {
  if ($("browse").hidden) $("folder").focus();
  else pickFolder();
}

function rulesById() {
  return new Map((state.data?.rules || []).map((r) => [r.id, r]));
}

// --- views ---------------------------------------------------------------------

function showView(view) {
  if (!VIEWS.includes(view)) view = "overview";
  if (state.view === "rules" && view !== "rules" && typeof isDirty === "function" && isDirty()) {
    if (!confirm("Leave without saving your rule changes?")) return;
    discard();
  }
  state.view = view;
  editor.view = view; // rules.js keys its save bar off this
  history.replaceState(null, "", view === "overview" ? location.pathname + location.search : `#${view}`);
  for (const button of document.querySelectorAll("[data-view]")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  for (const v of VIEWS) $(`${v}-page`).hidden = v !== view;
  if (view !== "rules") showSaveError(null);
  if (view === "rules") loadSettings();
  updateSavebar();
  window.scrollTo(0, 0);
}

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => showView(button.dataset.view));
}

// Jump to Problems with a filter set, from Overview's cards.
function showProblems({ rule = null, fixableOnly = false } = {}) {
  state.rule = rule;
  state.fixableOnly = fixableOnly;
  state.severities = new Set(["error", "warn"]);
  state.query = "";
  renderProblems();
  showView("problems");
}

// --- checking --------------------------------------------------------------

async function check(folder) {
  $("folder").value = folder;
  $("check").disabled = true;
  $("check").textContent = "Checking…";
  for (const v of VIEWS) $(`${v}-page`).setAttribute("aria-busy", "true");
  try {
    const data = await api("/api/check", { folder });
    const sameFolder = data.folder === state.data?.folder;
    if (!sameFolder) {
      state.rule = null; // a new folder starts unfiltered; checking again keeps the filters
      state.fixableOnly = false;
      state.query = "";
    }
    // How many problems this folder had before, so reaching zero can say what changed.
    state.before = sameFolder ? state.data.errors + state.data.warnings : null;
    state.data = data;
    $("folder").value = data.folder; // the folder as resolved, so "Check again" matches it
    render();
    loadRecent();
    rulesFolderChecked(data.folder);
    // A new folder opens on its overview; checking the same one again stays where you are.
    if (!sameFolder && state.view !== "rules") showView("overview");
  } catch (error) {
    showError(error.message);
  } finally {
    $("check").disabled = false;
    for (const v of VIEWS) $(`${v}-page`).removeAttribute("aria-busy");
    updateCheckButton();
  }
}

function showError(message) {
  state.data = null;
  render();
  $("overview-page").prepend(
    el("div", { class: "error-box", role: "alert" },
      el("h2", {}, "Couldn't check this folder"),
      el("pre", {}, message)));
  showView("overview");
}

function render() {
  const total = state.data ? state.data.errors + state.data.warnings : 0;
  $("problems-count").textContent = total > 999 ? "999+" : String(total);
  $("problems-count").hidden = total === 0;
  renderOverview();
  renderProblems();
  updateCheckButton();
}

// --- overview: welcome, or the folder's health at a glance ------------------------------

function renderOverview() {
  const page = $("overview-page");
  if (!state.data) return page.replaceChildren(...welcome());
  const d = state.data;
  const total = d.errors + d.warnings;
  const inv = d.inventory;
  page.replaceChildren(
    pageHeader(folderName(d.folder), "Overview: how healthy this folder is, and what to do next."),
    el("div", { class: "bento" },
      healthCard(d, total),
      nextStepCard(d, total),
      total ? byCheckCard(d) : null,
      folderCard(inv),
      listCard("Heaviest meshes", "triangles", inv.heaviest_meshes, (m) => plural(m.triangles, "triangle")),
      listCard("Largest textures", "pixels", inv.largest_textures, (t) => `${t.width} × ${t.height}`),
      listCard("Largest files", "on disk", inv.largest_files, (f) => size(f.size)),
      rulesCard(d)));
}

function healthCard(d, total) {
  const withProblems = Object.keys(d.files).length;
  const passing = d.files_checked - withProblems;
  const clean = total === 0;
  const earned = clean && state.before > 0;
  const tile = (label, value, iconName) =>
    el("div", { class: "stat" },
      el("div", { class: "stat-label" }, iconName ? icon(iconName) : null, label),
      el("div", { class: "stat-value" }, value.toLocaleString()));
  return card({ class: `span-2 health${clean ? " clean" : ""}${earned ? " earned" : ""}` },
    el("div", { class: "health-head" },
      clean ? el("div", { class: "clean-mark" }, icon("cube")) : null,
      el("div", {},
        el("h2", { class: "health-title" },
          clean ? "All clear" : `${plural(total, "problem")} in ${plural(withProblems, "file")}`),
        el("p", { class: "muted" }, clean
          ? (earned ? `Down from ${plural(state.before, "problem")} to none. ` : "") +
            (d.files_checked === 1 ? "The file passes every check." : `All ${d.files_checked.toLocaleString()} files pass every check.`)
          : `${passing.toLocaleString()} of ${plural(d.files_checked, "file")} pass every check.`))),
    el("div", { class: "stats" },
      tile("Files checked", d.files_checked),
      tile("Passing", passing, "ok"),
      tile("Errors", d.errors, "error"),
      tile("Warnings", d.warnings, "warn")));
}

// The single most useful thing to do now, worked out from the result.
function nextStepCard(d, total) {
  const rules = rulesById();
  let title, text, action;
  if (total === 0) {
    title = "Nothing to fix";
    text = "Keep it that way: add a rule for your team's own conventions, or check another folder.";
    action = el("button", { type: "button", class: "secondary", onclick: () => showView("rules") }, "Open rules", icon("arrow"));
  } else if (d.fixable.length) {
    const n = d.fixable.length;
    title = `${plural(n, "file")} can be fixed in one click`;
    text = "Rename badly named files, repair texture paths and move duplicate copies to the trash. You see every change before it's made.";
    action = el("button", { type: "button", onclick: () => showProblems({ fixableOnly: true }) }, icon("wand"), "Show fixable files");
  } else {
    const counts = countBy(d.findings.filter((f) => f.severity === (d.errors ? "error" : "warn")), "rule");
    const [ruleId, n] = [...counts].sort((a, b) => b[1] - a[1])[0];
    const rule = rules.get(ruleId);
    title = `Start with ${rule?.label || ruleId}: ${plural(n, d.errors ? "error" : "warning")}`;
    text = rule?.how || "";
    action = el("button", { type: "button", onclick: () => showProblems({ rule: ruleId }) }, "Show them", icon("arrow"));
  }
  return card({ class: "span-2 next" },
    cardTitle("Next step"),
    el("p", { class: "next-title" }, title),
    el("p", { class: "muted" }, text),
    el("div", { class: "card-actions" }, action));
}

function countBy(items, key) {
  const counts = new Map();
  for (const item of items) counts.set(item[key], (counts.get(item[key]) || 0) + 1);
  return counts;
}

// Problems per check as bars: one series, so no legend; colour + icon say error or warning.
function byCheckCard(d) {
  const counts = countBy(d.findings, "rule");
  const errors = countBy(d.findings.filter((f) => f.severity === "error"), "rule");
  const rows = d.rules.filter((r) => counts.has(r.id)).sort((a, b) => counts.get(b.id) - counts.get(a.id));
  const max = Math.max(...rows.map((r) => counts.get(r.id)));
  return card({ class: "span-2" },
    cardTitle("Problems by check", "Select one to see its problems"),
    el("ul", { class: "bars" }, rows.map((r) => {
      const n = counts.get(r.id);
      const sev = errors.has(r.id) ? "error" : "warn";
      return el("li", {}, el("button", {
        type: "button", class: `bar-row ${sev}`, title: `${r.label}: ${r.description}`,
        onclick: () => showProblems({ rule: r.id }),
      },
        el("span", { class: "bar-label" }, icon(sev, sev === "error" ? "Errors" : "Warnings"), r.label),
        el("span", { class: "bar-track" }, el("span", { class: "bar-fill", style: `width:${Math.max(4, (n / max) * 100)}%` })),
        el("span", { class: "bar-value" }, n.toLocaleString())));
    })));
}

function folderCard(inv) {
  const types = inv.by_type.slice(0, 6);
  const rest = inv.by_type.length - types.length;
  return card({ class: "span-2" },
    cardTitle("In this folder", `${plural(inv.files, "file")} · ${size(inv.total_size)}`),
    el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, el("th", {}, "Type"), el("th", {}, "Files"), el("th", {}, "Size"))),
      el("tbody", {}, types.map((t) =>
        el("tr", {}, el("td", {}, el("code", {}, t.type)), el("td", {}, t.count.toLocaleString()), el("td", {}, size(t.size)))))),
    rest > 0 ? el("p", { class: "muted small" }, `and ${plural(rest, "more type")}`) : null,
    inv.unreadable ? el("p", { class: "muted small" }, `${plural(inv.unreadable, "file")} couldn't be read: see File type in Problems.`) : null);
}

// A short ranked list; hidden when there's nothing to rank, so no card shows zeros.
function listCard(title, unit, items, value) {
  if (!items.length) return null;
  return card({},
    cardTitle(title, unit),
    el("ol", { class: "ranked" }, items.map((item) =>
      el("li", {}, pathLabel(item.path), el("span", { class: "value" }, value(item))))));
}

function rulesCard(d) {
  const custom = d.rules.filter((r) => r.custom).length;
  const off = d.rules.filter((r) => r.severity === "off").length;
  return card({},
    cardTitle("Rules"),
    el("p", {}, d.config
      ? el("span", { title: d.config }, "From ", el("code", {}, shortConfigPath(d.config)))
      : "No assetlint.toml here, so the default rules apply."),
    el("p", { class: "muted small" },
      [d.preset ? `${d.preset[0].toUpperCase()}${d.preset.slice(1)} preset` : null,
       `${d.rules.length - off} checks on`, off ? `${off} off` : null,
       custom ? plural(custom, "custom rule") : null].filter(Boolean).join(" · ")),
    el("div", { class: "card-actions" },
      el("button", { type: "button", class: "secondary", onclick: () => showView("rules") }, "Open rules", icon("arrow"))));
}

// Before any check: what the app is, how it works, what it checks, and recent folders.
function welcome() {
  const recent = state.info.recent || [];
  return [
    el("div", { class: "bento" },
      card({ class: "span-4 hero" },
        el("h1", {}, "Check an asset folder"),
        el("p", { class: "lede" }, "Asset Lint finds problems in 3D asset folders before they reach the game or the client: bad names, oversized files and textures, triangle budgets, duplicate copies and broken texture paths."),
        el("div", { class: "card-actions" },
          el("button", { type: "button", onclick: chooseFolder }, state.info.can_browse ? "Choose a folder…" : "Paste a folder path above"),
          state.info.can_browse ? el("span", { class: "muted small" }, "or paste a path in the bar above") : null)),
      card({ class: "span-2" },
        cardTitle("How it works"),
        el("ol", { class: "steps" },
          el("li", {}, el("strong", {}, "Choose a folder."), " Every model and texture in it is checked against your rules."),
          el("li", {}, el("strong", {}, "See what's wrong and why."), " Problems are grouped by check, each with how to fix it."),
          el("li", {}, el("strong", {}, "Fix it, or tune the rules."), " Many problems fix in one click; rules live in the folder's assetlint.toml, shared with CI."))),
      card({ class: "span-2" },
        cardTitle("What it checks"),
        el("ul", { class: "checks" }, state.info.checks.map((c) =>
          el("li", {}, el("strong", {}, c.label), el("span", { class: "muted" }, c.description))))),
      recent.length ? card({ class: "span-4" },
        cardTitle("Recent folders"),
        el("ul", { class: "recent" }, recent.map((f) => {
          const parts = f.split(/[\\/]/).filter(Boolean);
          const name = parts.pop() || f;
          return el("li", {}, el("button", { type: "button", title: f, onclick: () => check(f) },
            el("span", { class: "name" }, name),
            el("span", { class: "where" }, parts.join(f.includes("\\") ? "\\" : "/"))));
        }))) : null),
  ];
}

// --- problems: one card per check, each with why it matters and how to fix ---------------

function visibleFindings() {
  const q = state.query.toLowerCase();
  const fixable = new Set(state.data.fixable);
  return state.data.findings.filter((f) =>
    state.severities.has(f.severity) &&
    (!state.rule || f.rule === state.rule) &&
    (!state.fixableOnly || fixable.has(f.path)) &&
    (!q || f.path.toLowerCase().includes(q) || f.message.toLowerCase().includes(q)));
}

function renderProblems() {
  const page = $("problems-page");
  const d = state.data;
  const purpose = "Every problem, grouped by check. Each check says why it matters and how to fix it.";
  if (!d) {
    return page.replaceChildren(pageHeader("Problems", purpose),
      card({ class: "empty-card" },
        el("p", {}, "No folder checked yet."),
        el("button", { type: "button", onclick: chooseFolder }, state.info.can_browse ? "Choose a folder…" : "Paste a folder path above")));
  }
  if (d.findings.length === 0) {
    const earned = state.before > 0;
    return page.replaceChildren(pageHeader("Problems", purpose),
      card({ class: `empty-card clean${earned ? " earned" : ""}` },
        el("div", { class: "clean-mark" }, icon("cube")),
        el("h2", {}, "All clear"),
        el("p", { class: "muted" }, earned
          ? `Down from ${plural(state.before, "problem")} to none.`
          : "Nothing in this folder breaks a rule.")));
  }
  page.replaceChildren(pageHeader("Problems", purpose), filterBar(), el("div", { id: "check-cards" }));
  renderCheckCards();
}

function filterBar() {
  const d = state.data;
  const counts = countBy(d.findings, "rule");
  if (state.rule && !counts.has(state.rule)) state.rule = null; // that check's problems are gone
  if (state.fixableOnly && !d.fixable.length) state.fixableOnly = false;
  const both = d.errors > 0 && d.warnings > 0;
  if (!both) state.severities = new Set(["error", "warn"]); // a hidden filter must not hide anything

  const chip = (label, pressed, onclick, ...extra) =>
    el("button", { type: "button", class: "chip", "aria-pressed": String(pressed), onclick }, extra[0] || null, el("span", {}, label), extra[1] || null);
  const n = (value) => el("span", { class: "n" }, value.toLocaleString());

  const severity = both ? ["error", "warn"].map((s) => chip(
    s === "error" ? "Errors" : "Warnings", state.severities.has(s),
    () => { state.severities.has(s) ? state.severities.delete(s) : state.severities.add(s); renderProblems(); },
    icon(s), n(s === "error" ? d.errors : d.warnings))) : [];
  const fixable = d.fixable.length ? [chip("Fixable in one click", state.fixableOnly,
    () => { state.fixableOnly = !state.fixableOnly; renderProblems(); }, icon("wand"), n(d.fixable.length))] : [];
  const rules = [chip("All checks", state.rule === null, () => { state.rule = null; renderProblems(); }, null, n(d.findings.length)),
    ...d.rules.filter((r) => counts.has(r.id)).map((r) => chip(r.label, state.rule === r.id,
      () => { state.rule = state.rule === r.id ? null : r.id; renderProblems(); }, null, n(counts.get(r.id))))];

  const search = el("input", {
    type: "search", id: "filter", placeholder: "Filter by file or message", value: state.query,
    "aria-label": "Filter by file or message", "aria-keyshortcuts": "Control+F",
    oninput: (e) => { state.query = e.target.value; renderCheckCards(); },
  });
  return card({ class: "filters", "aria-label": "Filters" },
    el("div", { class: "filters-top" },
      el("div", { class: "chips" }, severity, fixable),
      el("div", { class: "search" }, search, el("kbd", { "aria-hidden": "true" }, "Ctrl F"))),
    el("div", { class: "chips" }, rules),
    el("p", { class: "shown", id: "shown" }));
}

function renderCheckCards() {
  const d = state.data;
  const findings = visibleFindings();
  $("shown").textContent = findings.length === d.findings.length
    ? "" : `Showing ${findings.length.toLocaleString()} of ${plural(d.findings.length, "problem")}`;
  const byRule = new Map();
  for (const f of findings) {
    if (!byRule.has(f.rule)) byRule.set(f.rule, new Map());
    const files = byRule.get(f.rule);
    if (!files.has(f.path)) files.set(f.path, []);
    files.get(f.path).push(f);
  }
  const cards = d.rules.filter((r) => byRule.has(r.id)).map((r) => checkCard(r, byRule.get(r.id)));
  $("check-cards").replaceChildren(...(cards.length ? cards
    : [card({ class: "empty-card" }, el("p", {}, "Nothing matches these filters."))]));
}

function checkCard(rule, files) {
  const all = [...files.values()].flat();
  const errors = all.filter((f) => f.severity === "error").length;
  const sev = errors ? "error" : "warn";
  const word = errors && errors < all.length ? `${plural(errors, "error")}, ${plural(all.length - errors, "warning")}`
    : plural(all.length, sev === "error" ? "error" : "warning");
  return card({ class: `check-card ${sev}` },
    el("header", { class: "check-head" },
      icon(sev),
      el("h2", {}, rule.label),
      el("span", { class: "check-count" }, `${word} in ${plural(files.size, "file")}`)),
    el("div", { class: "explain" },
      el("p", {}, el("strong", {}, "Why it matters. "), rule.why || rule.description),
      el("p", {}, el("strong", {}, "How to fix. "), rule.how)),
    el("ul", { class: "file-rows" }, [...files].map(([path, items]) => fileRow(path, items))));
}

function fileRow(path, items) {
  const facts = state.data.files[path] || {};
  const tags = [];
  if (facts.size != null) tags.push(size(facts.size));
  if (facts.triangles != null) tags.push(plural(facts.triangles, "triangle"));
  if (facts.width != null) tags.push(`${facts.width} × ${facts.height}`);
  const naming = items.some((f) => f.rule === "naming") ? facts.naming : null;
  return el("li", { class: "file-row" },
    el("div", { class: "file-line" },
      pathLabel(path),
      el("span", { class: "facts" }, tags.map((t) => el("span", { class: "fact" }, t))),
      fixButton(path)),
    el("ul", { class: "messages" }, items.map((f) =>
      el("li", { class: f.severity }, icon(f.severity, f.severity === "warn" ? "Warning" : "Error"), f.message))),
    naming ? el("p", { class: "hint-line" },
      naming.prefix ? ["Needs the ", el("code", {}, naming.prefix), " prefix. "] : null,
      "Would pass as ", el("code", {}, naming.suggested), ".") : null);
}

// --- recent folders, the folder bar and start-up -----------------------------------

function showRecent(recent) {
  state.info.recent = recent;
  $("recent").replaceChildren(...recent.map((f) => el("option", { value: f })));
  if (!state.data) renderOverview();
}

async function loadRecent() {
  try {
    showRecent((await api("/api/info")).recent);
  } catch { /* not important */ }
}

$("folder-form").addEventListener("submit", (event) => {
  event.preventDefault();
  check($("folder").value);
});

// "Check again" when the box holds the folder already shown, so the button says what it'll do.
function updateCheckButton() {
  const same = state.data && $("folder").value.trim() === state.data.folder;
  if (!$("check").disabled) $("check").textContent = same ? "Check again" : "Check";
}
$("folder").addEventListener("input", updateCheckButton);

async function pickFolder() {
  try {
    const { folder } = await api("/api/browse", {});
    if (folder) check(folder);
  } catch (error) {
    toast(error.message);
  }
}
$("browse").addEventListener("click", pickFolder);

// Shortcuts: Ctrl+F filters the problems, F5 checks the folder again, Ctrl+S saves the rules.
document.addEventListener("keydown", (event) => {
  const ctrl = event.ctrlKey || event.metaKey;
  if (ctrl && event.key.toLowerCase() === "f" && state.data?.findings.length) {
    event.preventDefault();
    if (state.view !== "problems") showView("problems");
    $("filter").focus();
    $("filter").select();
  } else if (event.key === "F5" || (ctrl && event.key.toLowerCase() === "r")) {
    event.preventDefault(); // a reload would drop unsaved rule changes
    if (state.data && !$("check").disabled) check(state.data.folder);
  } else if (ctrl && event.key.toLowerCase() === "s" && typeof isDirty === "function" && isDirty()) {
    event.preventDefault();
    $("save").click();
  }
});

(async () => {
  try {
    const info = await api("/api/info");
    state.info = info;
    $("browse").hidden = !info.can_browse;
    showRecent(info.recent);
    const view = location.hash.slice(1);
    if (VIEWS.includes(view)) showView(view);
    if (info.start_folder) check(info.start_folder);
  } catch (error) {
    $("overview-page").replaceChildren(el("div", { class: "error-box", role: "alert" },
      el("h2", {}, "Can't reach the app"),
      el("pre", {}, `${error.message}\n\nOpen the app with the link that \`assetlint app\` printed.`)));
  }
})();
