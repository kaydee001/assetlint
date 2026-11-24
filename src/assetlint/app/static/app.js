// Asset Lint app: fetches results from the local server and shows them.
// All logic lives in Python; this file only displays and sends requests.
"use strict";

const token = (() => {
  const fromUrl = new URLSearchParams(location.search).get("token");
  if (fromUrl) sessionStorage.setItem("assetlint-token", fromUrl);
  return fromUrl || sessionStorage.getItem("assetlint-token") || "";
})();

const $ = (id) => document.getElementById(id);
const state = { data: null, severities: new Set(["error", "warn"]), rule: null, query: "" };

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

// --- small DOM helpers -----------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child);
  }
  return node;
}

// Drawn icons, one 16px grid and one stroke weight. `label` makes it announced; else it's decorative.
const ICONS = {
  close: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
  error: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5.25v3.25M8 10.75v.01"/>',
  warn: '<path d="M8 2.75l5.75 10H2.25z"/><path d="M8 6.75v2.5M8 11.25v.01"/>',
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
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join("/");
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (box.hidden = true), 4000);
}

// --- checking --------------------------------------------------------------

async function check(folder) {
  $("folder").value = folder;
  $("check").disabled = true;
  $("check").textContent = "Checking…";
  $("results").setAttribute("aria-busy", "true");
  try {
    const data = await api("/api/check", { folder });
    const sameFolder = data.folder === state.data?.folder;
    if (!sameFolder) {
      state.rule = null; // a new folder starts unfiltered; checking again keeps the filters
      state.query = "";
    }
    // How many problems this folder had before, so reaching zero can say what changed.
    state.before = sameFolder ? state.data.errors + state.data.warnings : null;
    state.data = data;
    $("folder").value = data.folder; // the folder as resolved, so "Check again" matches it
    render();
    loadRecent();
    afterCheck(state.data.folder);
  } catch (error) {
    showError(error.message);
  } finally {
    $("check").disabled = false;
    $("results").removeAttribute("aria-busy");
    updateCheckButton();
  }
}

function showError(message) {
  state.data = null;
  $("sidebar").hidden = true;
  $("results").replaceChildren(
    el("div", { class: "error-box", role: "alert" },
      el("h1", {}, "Couldn't check this folder"),
      el("pre", {}, message)),
  );
}

// --- rendering ---------------------------------------------------------------

function visibleFindings() {
  const q = state.query.toLowerCase();
  return state.data.findings.filter((f) =>
    state.severities.has(f.severity) &&
    (!state.rule || f.rule === state.rule) &&
    (!q || f.path.toLowerCase().includes(q) || f.message.toLowerCase().includes(q)));
}

function configNote(data) {
  return data.config
    ? el("span", { title: data.config }, "Rules from ", el("code", {}, shortConfigPath(data.config)))
    : "No assetlint.toml here, so the default rules apply.";
}

function render() {
  const data = state.data;
  const total = data.errors + data.warnings;
  $("problems-count").textContent = total ? String(total) : "";
  updateCheckButton();
  if (data.findings.length === 0) {
    $("sidebar").hidden = true; // nothing to filter
    $("results").replaceChildren(cleanState(data));
    return;
  }

  $("sidebar").hidden = false;
  renderSummary(data);
  renderSeverityFilters(data);
  renderRuleFilters(data);
  $("config").replaceChildren(configNote(data));

  const search = el("input", {
    type: "search", id: "filter", placeholder: "Filter by file or message", value: state.query,
    "aria-label": "Filter by file or message", "aria-keyshortcuts": "Control+F",
    oninput: (e) => { state.query = e.target.value; renderList(); },
  });
  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "search" }, search, el("kbd", { "aria-hidden": "true" }, "Ctrl F")),
    el("span", { class: "shown", id: "shown" }));
  $("results").replaceChildren(toolbar, el("div", { id: "list" }));
  renderList();
}

// The one moment the app celebrates: a folder with nothing left to fix. When this check
// followed one with problems, say what changed; the cube draws itself once.
function cleanState(data) {
  const fixedSome = state.before > 0;
  return el("div", { class: `empty clean${fixedSome ? " earned" : ""}` },
    el("div", { class: "clean-mark" }, icon("cube")),
    el("h1", {}, "All clear"),
    el("p", {}, fixedSome
      ? `Down from ${plural(state.before, "problem")} to none. ${passing(data.files_checked)}`
      : passing(data.files_checked)),
    el("p", { class: "config" }, configNote(data)));
}

function passing(n) {
  return n === 1 ? "The file passes every rule." : `All ${n} files pass every rule.`;
}

function renderList(findings = visibleFindings()) {
  const total = state.data.findings.length;
  // Only worth saying when filters hide some; the sidebar already has the total.
  $("shown").textContent = findings.length === total ? "" : `Showing ${findings.length} of ${total}`;

  const byFile = new Map();
  for (const f of findings) {
    if (!byFile.has(f.path)) byFile.set(f.path, []);
    byFile.get(f.path).push(f);
  }
  const files = [...byFile].map(([path, items]) => fileCard(path, items));
  $("list").replaceChildren(
    ...(files.length ? files : [el("p", { class: "no-match" }, "Nothing matches these filters.")]));
}

function fileCard(path, items) {
  const slash = path.lastIndexOf("/");
  const dir = slash >= 0 ? path.slice(0, slash + 1) : "";
  const name = path.slice(slash + 1);
  const rules = new Map(state.data.rules.map((r) => [r.id, r]));
  return el("article", { class: "file" },
    el("div", { class: "file-head" },
      el("span", { class: "path" }, el("span", { class: "dir" }, dir), el("span", { class: "name" }, name)),
      fixButton(path)),
    items.map((f) =>
      el("div", { class: `finding ${f.severity}` },
        icon(f.severity, f.severity === "warn" ? "Warning" : "Error"),
        el("span", { class: "rule", title: rules.get(f.rule)?.description || "" },
          rules.get(f.rule)?.label || f.rule),
        el("span", { class: "msg" }, f.message))));
}

function renderSummary(data) {
  $("summary").replaceChildren(
    el("div", { class: "count" }, plural(data.errors + data.warnings, "problem")),
    el("div", { class: "detail" },
      `in ${new Set(data.findings.map((f) => f.path)).size} of ${plural(data.files_checked, "file")}`));
}

function renderSeverityFilters(data) {
  // Only worth a filter when both kinds are present.
  const both = data.errors > 0 && data.warnings > 0;
  $("severity-section").hidden = !both;
  if (!both) {
    state.severities = new Set(["error", "warn"]); // a hidden filter must not hide anything
    return;
  }
  const make = (severity, label, count) =>
    el("button", {
      type: "button", class: `toggle ${severity}`, "aria-pressed": String(state.severities.has(severity)),
      onclick: () => {
        state.severities.has(severity) ? state.severities.delete(severity) : state.severities.add(severity);
        render();
      },
    }, icon(severity), el("span", {}, label), el("span", { class: "n" }, count));
  $("severity-filters").replaceChildren(
    make("error", "Errors", data.errors),
    make("warn", "Warnings", data.warnings));
}

function renderRuleFilters(data) {
  const counts = new Map();
  for (const f of data.findings) counts.set(f.rule, (counts.get(f.rule) || 0) + 1);
  if (state.rule && !counts.has(state.rule)) state.rule = null; // that rule's problems are gone

  const button = (id, label, n, title = "") =>
    el("li", {}, el("button", {
      type: "button", title, "aria-pressed": String(state.rule === id),
      onclick: () => { state.rule = state.rule === id || id === null ? null : id; render(); },
    }, el("span", {}, label), el("span", { class: "n" }, n)));

  // Only the rules that found something: the Rules tab lists every rule and its settings.
  const items = data.rules
    .filter((rule) => counts.has(rule.id))
    .map((rule) => button(rule.id, rule.label || rule.id, counts.get(rule.id), rule.description));
  $("rule-filters").replaceChildren(button(null, "All rules", data.findings.length), ...items);
}

// --- recent folders and start-up ----------------------------------------------

function showRecent(recent) {
  $("recent").replaceChildren(...recent.map((f) => el("option", { value: f })));
  $("recent-heading").hidden = recent.length === 0;
  $("recent-list").replaceChildren(...recent.map((f) => {
    const parts = f.split(/[\\/]/).filter(Boolean);
    const name = parts.pop() || f;
    return el("li", {}, el("button", { type: "button", title: f, onclick: () => check(f) },
      el("span", { class: "name" }, name),
      el("span", { class: "where" }, parts.join(f.includes("\\") ? "\\" : "/"))));
  }));
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
$("choose").addEventListener("click", () => ($("browse").hidden ? $("folder").focus() : pickFolder()));

// Shortcuts: Ctrl+F filters the problems, F5 checks the folder again, Ctrl+S saves the rules.
document.addEventListener("keydown", (event) => {
  const ctrl = event.ctrlKey || event.metaKey;
  if (ctrl && event.key.toLowerCase() === "f" && $("filter") && $("rules-page").hidden) {
    event.preventDefault();
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
    $("browse").hidden = !info.can_browse;
    $("choose").textContent = info.can_browse ? "Choose a folder…" : "Paste a folder path above";
    showRecent(info.recent);
    if (info.start_folder) check(info.start_folder);
  } catch (error) {
    showError(`${error.message}\n\nOpen the app with the link that \`assetlint app\` printed.`);
  }
})();
