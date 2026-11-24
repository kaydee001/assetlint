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
  try {
    state.data = await api("/api/check", { folder });
    state.rule = null;
    state.query = "";
    render();
    loadRecent();
    afterCheck(state.data.folder);
  } catch (error) {
    showError(error.message);
  } finally {
    $("check").disabled = false;
    $("check").textContent = "Check";
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

function render() {
  const data = state.data;
  $("sidebar").hidden = false;
  renderSummary(data);
  renderSeverityFilters(data);
  renderRuleFilters(data);
  $("config").replaceChildren(
    data.config
      ? el("span", { title: data.config }, "Rules from ", el("code", {}, shortConfigPath(data.config)))
      : "No assetlint.toml found, so the default rules apply.");

  if (data.findings.length === 0) {
    $("results").replaceChildren(
      el("div", { class: "empty clean" },
        el("h1", {}, "No problems found"),
        el("p", {}, `All ${plural(data.files_checked, "file")} pass every rule.`)));
    return;
  }

  const findings = visibleFindings();
  const search = el("input", {
    type: "search", placeholder: "Filter by file or message", value: state.query,
    "aria-label": "Filter by file or message",
    oninput: (e) => { state.query = e.target.value; renderList(); },
  });
  const toolbar = el("div", { class: "toolbar" }, search, el("span", { class: "shown", id: "shown" }));
  $("results").replaceChildren(toolbar, el("div", { id: "list" }));
  renderList(findings);
}

function renderList(findings = visibleFindings()) {
  const total = state.data.findings.length;
  $("shown").textContent = findings.length === total
    ? plural(total, "problem")
    : `${findings.length} of ${plural(total, "problem")}`;

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
  const ext = name.includes(".") ? name.split(".").pop().toUpperCase() : "";
  const rules = new Map(state.data.rules.map((r) => [r.id, r]));
  return el("article", { class: "file" },
    el("div", { class: "file-head" },
      el("span", { class: "type" }, ext),
      el("span", {}, el("span", { class: "dir" }, dir), el("span", { class: "name" }, name)),
      fixButton(path)),
    items.map((f) =>
      el("div", { class: "finding" },
        el("span", { class: `sev ${f.severity}` }, f.severity === "warn" ? "warning" : "error"),
        el("span", { class: "rule", title: rules.get(f.rule)?.description || "" }, f.rule),
        el("span", { class: "msg" }, f.message))));
}

function renderSummary(data) {
  const summary = $("summary");
  summary.classList.toggle("clean", data.findings.length === 0);
  const problems = data.errors + data.warnings;
  summary.replaceChildren(
    el("div", { class: "count" }, problems ? plural(problems, "problem") : "All clear"),
    el("div", { class: "detail" },
      problems
        ? `${plural(data.errors, "error")}, ${plural(data.warnings, "warning")} in ${plural(data.files_checked, "file")}`
        : `${plural(data.files_checked, "file")} checked`));
}

function renderSeverityFilters(data) {
  const make = (severity, label, color, count) =>
    el("button", {
      type: "button", class: "toggle", "aria-pressed": String(state.severities.has(severity)),
      onclick: () => {
        state.severities.has(severity) ? state.severities.delete(severity) : state.severities.add(severity);
        render();
      },
    }, el("span", { class: "dot", style: `background:${color}` }), `${label} ${count}`);
  $("severity-filters").replaceChildren(
    make("error", "Errors", "var(--error)", data.errors),
    make("warn", "Warnings", "var(--warn)", data.warnings));
}

function renderRuleFilters(data) {
  const counts = new Map();
  for (const f of data.findings) counts.set(f.rule, (counts.get(f.rule) || 0) + 1);
  const all = el("li", {}, el("button", {
    type: "button", "aria-pressed": String(state.rule === null),
    onclick: () => { state.rule = null; render(); },
  }, el("span", {}, "All rules"), el("span", { class: "n" }, data.findings.length)));

  const items = data.rules.map((rule) => {
    const off = rule.severity === "off";
    const n = counts.get(rule.id) || 0;
    return el("li", {}, el("button", {
      type: "button", title: rule.description, disabled: off,
      class: off ? "off" : n === 0 ? "zero" : "", "aria-pressed": String(state.rule === rule.id),
      onclick: () => { state.rule = state.rule === rule.id ? null : rule.id; render(); },
    }, el("span", {}, rule.id), el("span", { class: "n" }, off ? "off" : n)));
  });
  $("rule-filters").replaceChildren(all, ...items);
}

// --- recent folders and start-up ----------------------------------------------

function showRecent(recent) {
  $("recent").replaceChildren(...recent.map((f) => el("option", { value: f })));
  $("recent-list").replaceChildren(
    ...recent.map((f) => el("li", {}, el("button", { type: "button", title: f, onclick: () => check(f) }, f))));
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

$("browse").addEventListener("click", async () => {
  try {
    const { folder } = await api("/api/browse", {});
    if (folder) check(folder);
  } catch (error) {
    toast(error.message);
  }
});

(async () => {
  try {
    const info = await api("/api/info");
    $("browse").hidden = !info.can_browse;
    showRecent(info.recent);
    if (info.start_folder) check(info.start_folder);
  } catch (error) {
    showError(`${error.message}\n\nOpen the app with the link that \`assetlint app\` printed.`);
  }
})();
