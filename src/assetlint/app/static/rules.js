// The Rules view: edit assetlint.toml through forms. Uses the helpers in app.js.
"use strict";

const SEVERITIES = [["error", "Error"], ["warn", "Warning"], ["off", "Off"]];

const editor = {
  view: "problems",
  folder: null,
  original: null, // settings as loaded, to work out what changed
  draft: null,    // what the form shows now
};

const clone = (value) => JSON.parse(JSON.stringify(value));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// --- switching views ---------------------------------------------------------

function showView(view) {
  editor.view = view;
  history.replaceState(null, "", view === "rules" ? "#rules" : location.pathname + location.search);
  for (const button of document.querySelectorAll("#tabs button")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  document.querySelector(".layout").hidden = view !== "problems";
  $("rules-page").hidden = view !== "rules";
  if (view === "rules") loadSettings();
  updateSavebar();
}

for (const button of document.querySelectorAll("#tabs button")) {
  button.addEventListener("click", () => {
    if (editor.view === "rules" && isDirty() && button.dataset.view !== "rules" &&
        !confirm("Leave without saving your rule changes?")) return;
    if (button.dataset.view === "problems" && isDirty()) discard();
    showView(button.dataset.view);
  });
}

// Called by app.js after every successful check.
function afterCheck(folder) {
  $("tabs").hidden = false;
  if (editor.folder !== folder) {
    editor.folder = folder;
    editor.original = editor.draft = null;
  }
  if (editor.view === "rules") loadSettings();
  else if (location.hash === "#rules") showView("rules");
}

// --- loading and saving ---------------------------------------------------------

async function loadSettings(force = false) {
  if (!editor.folder) {
    $("rules-page").replaceChildren(el("p", { class: "section-help" }, "Check a folder first."));
    return;
  }
  if (editor.draft && !force) return renderRules();
  try {
    editor.original = await api("/api/settings", { folder: editor.folder });
    editor.draft = clone(editor.original);
    renderRules();
  } catch (error) {
    $("rules-page").replaceChildren(
      el("div", { class: "error-box", role: "alert" },
        el("h1", {}, "Couldn't read the rules"), el("pre", {}, error.message)));
  }
}

function changes() {
  const out = {};
  const o = editor.original, d = editor.draft;
  if (o.preset !== d.preset) out.preset = d.preset;
  if (!same(o.exclude, d.exclude)) out.exclude = d.exclude;
  if (!same(o.overrides, d.overrides)) out.overrides = d.overrides;
  if (!same(o.custom, d.custom)) out.custom = d.custom;

  const rules = {};
  d.rules.forEach((rule, i) => {
    const before = o.rules[i];
    const keys = {};
    // Only keys that changed are sent, so the file's other lines (and comments) stay as they are.
    if (!same(before.severity, rule.severity)) keys.severity = rule.severity.set ? rule.severity.value : null;
    rule.fields.forEach((field, j) => {
      const was = before.fields[j];
      if (was.set !== field.set || !same(was.value, field.value)) {
        keys[field.key] = field.set ? field.value : null;
      }
    });
    if (Object.keys(keys).length) rules[rule.id] = keys;
  });
  if (Object.keys(rules).length) out.rules = rules;
  return out;
}

function isDirty() {
  return Boolean(editor.original && Object.keys(changes()).length);
}

function updateSavebar() {
  $("savebar").hidden = !(editor.view === "rules" && isDirty());
}

function discard() {
  editor.draft = clone(editor.original);
  renderRules();
}

async function save() {
  const button = $("save");
  button.disabled = true;
  try {
    const result = await api("/api/settings/save", { folder: editor.folder, changes: changes() });
    toast(result.created ? `Created ${result.path}` : `Saved ${result.path}`);
    await loadSettings(true);
    await check(editor.folder);
  } catch (error) {
    alert(`Not saved:\n\n${error.message}`);
  } finally {
    button.disabled = false;
    updateSavebar();
  }
}

$("save").addEventListener("click", save);
$("discard").addEventListener("click", discard);
window.addEventListener("beforeunload", (event) => {
  if (isDirty()) event.preventDefault();
});

// --- rendering --------------------------------------------------------------------

function changed() {
  updateSavebar();
}

function renderRules() {
  const d = editor.draft;
  $("rules-page").replaceChildren(
    el("header", {},
      el("h1", {}, "Rules"),
      el("p", { class: "where", title: d.path },
        d.exists ? "In " : "Saving creates ",
        el("code", {}, shortConfigPath(d.path)),
        d.exists ? ", which the command line and CI also read." : ".")),
    presetSection(d),
    el("section", {},
      el("h2", {}, "Checks"),
      el("div", { class: "rule-grid" }, d.rules.map((r, i) => ruleCard(r, i)))),
    customSection(d),
    overridesSection(d),
    excludeSection(d),
  );
  updateSavebar();
}

function presetSection(d) {
  const description = el("p", { class: "preset-description" });
  const options = [{ id: null, label: "None", description: "Asset Lint's own defaults." }, ...d.presets];
  const buttons = options.map((p) =>
    el("button", {
      type: "button", class: "preset", "aria-pressed": String(d.preset === p.id),
      onclick: () => {
        d.preset = p.id;
        renderRules();
        toast("Preset changed. Save to see its settings in the checks below.");
      },
    }, p.label));
  description.textContent = (options.find((p) => p.id === d.preset)?.description || "") +
    (d.preset ? " Your own settings below win over the preset." : "");
  return el("section", {},
    el("h2", {}, "Preset"),
    el("div", { class: "presets segmented", role: "group", "aria-label": "Preset" }, buttons),
    description);
}

function ruleCard(rule, ruleIndex) {
  const card = el("article", { class: `rule-card${rule.severity.value === "off" ? " is-off" : ""}` });
  card.append(
    el("div", { class: "rule-top" },
      el("div", {}, el("h3", {}, rule.id), el("p", {}, rule.description)),
      severityControlFor(rule, card)),
    rule.fields.length
      ? el("div", { class: "rule-fields" }, rule.fields.map((f, i) => fieldRow(f, ruleIndex, i)))
      : "");
  return card;
}

function severityControlFor(rule, card) {
  return severityControl(rule.severity.value, (value) => {
    rule.severity = { value, set: true };
    card.classList.toggle("is-off", value === "off");
    card.querySelector(".segmented").replaceWith(severityControlFor(rule, card));
    changed();
  });
}

function severityControl(current, onPick) {
  return el("div", { class: "segmented", role: "group", "aria-label": "Severity" },
    SEVERITIES.map(([value, label]) =>
      el("button", {
        type: "button", class: value, "aria-pressed": String(current === value),
        onclick: () => onPick(value),
      }, label)));
}

function fieldRow(field, ruleIndex, fieldIndex) {
  const id = `f-${ruleIndex}-${fieldIndex}`;
  const status = el("span", { class: "from" }, field.set ? "" : editor.draft.preset ? "default or preset" : "default");
  const reset = el("button", {
    type: "button", class: "reset", hidden: !field.set,
    onclick: () => {
      // Back to what applies without this setting. If the file set it, that's unknown
      // until saved, so the field shows empty ("default") until then.
      const was = editor.original.rules[ruleIndex].fields[fieldIndex];
      field.set = false;
      field.value = was.set ? null : was.value;
      renderRules();
    },
  }, "reset");
  const control = valueInput(field.kind, field.value, (value) => {
    field.value = value;
    field.set = true;
    status.textContent = "";
    reset.hidden = false;
    changed();
  }, { id, inherited: !field.set, valueKind: field.value_kind, label: field.label });
  return el("div", { class: "field" },
    field.kind === "bool" ? "" : el("label", { for: id }, field.label, status, reset),
    control,
    field.help ? el("div", { class: "hint" }, field.help) : "");
}

// One input for a value of a given kind; calls onChange with the parsed value (null = empty).
function valueInput(kind, value, onChange, opts = {}) {
  const cls = opts.inherited ? "inherited" : "";
  switch (kind) {
    case "bool":
      return el("label", { class: "check" },
        el("input", { type: "checkbox", id: opts.id, checked: Boolean(value),
          onchange: (e) => onChange(e.target.checked) }),
        opts.label || "");
    case "int":
      return el("input", { type: "number", min: "1", step: "1", id: opts.id, class: cls,
        value: value ?? "", placeholder: "no limit",
        oninput: (e) => onChange(e.target.value === "" ? null : Math.max(1, Math.round(Number(e.target.value)))) });
    case "size":
      return el("input", { type: "text", id: opts.id, class: cls, value: value ?? "", placeholder: "no limit, e.g. 50MB",
        oninput: (e) => onChange(e.target.value.trim() || null) });
    case "extensions":
      return el("input", { type: "text", id: opts.id, class: cls, value: (value || []).join(", "),
        placeholder: "any type, e.g. .glb, .png",
        oninput: (e) => {
          const list = e.target.value.split(/[\s,]+/).filter(Boolean);
          onChange(list.length ? list : null);
        } });
    case "map":
      return mapInput(value || {}, onChange, opts.valueKind);
    case "lines":
      return el("textarea", { id: opts.id, spellcheck: false, value: (value || []).join("\n"),
        placeholder: opts.placeholder || "",
        oninput: (e) => {
          const list = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean);
          onChange(list.length ? list : null);
        } });
    default: // text
      return el("input", { type: "text", id: opts.id, class: cls, value: value ?? "", spellcheck: false,
        oninput: (e) => onChange(e.target.value === "" ? null : e.target.value) });
  }
}

function mapInput(map, onChange, valueKind) {
  const rows = Object.entries(map);
  const box = el("div", { class: "map-rows" });
  const emit = () => {
    const out = {};
    for (const [k, v] of rows) if (k.trim() && String(v).trim()) out[k.trim()] = v;
    onChange(Object.keys(out).length ? out : null);
  };
  const draw = () => {
    box.replaceChildren(
      ...rows.map((row, i) => el("div", { class: "map-row" },
        el("input", { type: "text", value: row[0], placeholder: ".png", "aria-label": "File type",
          oninput: (e) => { row[0] = e.target.value; emit(); } }),
        el("input", { type: "text", value: row[1], placeholder: valueKind === "size" ? "8MB" : "T_",
          "aria-label": "Value", oninput: (e) => { row[1] = e.target.value; emit(); } }),
        el("button", { type: "button", class: "icon-button", title: "Remove", "aria-label": "Remove",
          onclick: () => { rows.splice(i, 1); draw(); emit(); } }, icon("close")))),
      el("button", { type: "button", class: "link-button",
        onclick: () => { rows.push(["", ""]); draw(); } }, "+ Add file type"));
  };
  draw();
  return box;
}

// --- custom rules ------------------------------------------------------------------

function customSection(d) {
  return el("section", {},
    el("h2", {}, "Your rules"),
    el("p", { class: "section-help" },
      "Rules for your team's workflow: pick the files, then what they must be. " +
      "Each requirement a file misses is one problem."),
    d.custom.map((rule, i) => customCard(rule, i, d.custom_fields)),
    el("button", { type: "button", class: "link-button", onclick: () => {
      d.custom.push({ id: nextRuleId(d.custom), severity: "error" });
      renderRules();
    } }, "+ Add rule"));
}

function nextRuleId(rules) {
  let n = rules.length + 1;
  while (rules.some((r) => r.id === `rule-${n}`)) n++;
  return `rule-${n}`;
}

function customCard(rule, index, fields) {
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  const requirements = fields.filter((f) => f.key !== "paths" && f.key !== "types");
  const list = el("div", { class: "rule-fields" });
  const unused = () => requirements.filter((f) => !(f.key in rule));

  const draw = () => {
    const rows = requirements.filter((f) => f.key in rule).map((f) => requirementRow(rule, f, draw));
    const spare = unused();
    list.replaceChildren(...rows,
      spare.length
        ? el("select", { class: "add-requirement", "aria-label": "Add a requirement", onchange: (e) => {
            const f = byKey[e.target.value];
            rule[f.key] = f.kind === "bool" ? true : null;
            draw(); changed();
          } },
          el("option", { value: "", selected: true, disabled: true }, "+ Add requirement…"),
          spare.map((f) => el("option", { value: f.key }, f.label)))
        : null);
  };
  draw();

  const id = `c-${index}`;
  const fieldBox = (key) => {
    const f = byKey[key];
    return el("div", { class: "field" },
      el("label", { for: `${id}-${key}` }, f.label),
      valueInput(f.kind, rule[key], (v) => { setOrDrop(rule, key, v); changed(); },
        { id: `${id}-${key}`, placeholder: key === "paths" ? "characters/\nprops/*_LOD0.*" : "" }),
      f.help ? el("div", { class: "hint" }, f.help) : "");
  };

  return el("article", { class: "card custom-rule" },
    el("div", { class: "custom-head" },
      el("div", { class: "field" },
        el("label", { for: `${id}-id` }, "Rule id"),
        el("input", { type: "text", id: `${id}-id`, value: rule.id || "", spellcheck: false,
          placeholder: "hero-textures", oninput: (e) => { rule.id = e.target.value.trim(); changed(); } })),
      el("div", { class: "field grow" },
        el("label", { for: `${id}-description` }, "What it checks"),
        el("input", { type: "text", id: `${id}-description`, class: "prose", value: rule.description || "",
          placeholder: "Hero textures are square and at most 4K",
          oninput: (e) => { setOrDrop(rule, "description", e.target.value.trim() || null); changed(); } })),
      severityControl(rule.severity || "error", (v) => { rule.severity = v; renderRules(); }),
      el("button", { type: "button", class: "secondary", onclick: () => {
        editor.draft.custom.splice(index, 1);
        renderRules();
      } }, "Remove")),
    el("div", { class: "custom-scope" }, fieldBox("paths"), fieldBox("types")),
    el("h3", { class: "custom-subhead" }, "Requirements"),
    list);
}

function requirementRow(rule, field, redraw) {
  return el("div", { class: "override setting-row" },
    el("span", { class: "requirement-label" }, field.label),
    el("div", {},
      valueInput(field.kind, rule[field.key], (v) => { rule[field.key] = v; changed(); }, { label: "Yes" }),
      field.help ? el("div", { class: "hint" }, field.help) : ""),
    el("button", { type: "button", class: "icon-button", title: "Remove requirement",
      "aria-label": "Remove requirement",
      onclick: () => { delete rule[field.key]; redraw(); changed(); } }, icon("close")));
}

function setOrDrop(obj, key, value) {
  if (value === null || value === undefined) delete obj[key];
  else obj[key] = value;
}

// --- folder overrides --------------------------------------------------------------

function overrideSettingOptions() {
  const options = [];
  for (const rule of editor.draft.rules) {
    options.push({ key: `${rule.id}.severity`, label: `${rule.id} · severity`, kind: "severity" });
    for (const f of rule.fields) {
      if (f.kind !== "map") options.push({ key: `${rule.id}.${f.key}`, label: `${rule.id} · ${f.label.toLowerCase()}`, kind: f.kind });
    }
  }
  return options;
}

function overridesSection(d) {
  const options = overrideSettingOptions();
  const cards = d.overrides.map((override, index) => overrideCard(override, index, options));
  return el("section", {},
    el("h2", {}, "Folder overrides"),
    el("p", { class: "section-help" },
      "Different settings for some folders, e.g. a bigger triangle budget for characters/. When several match, the last one wins."),
    cards,
    el("button", { type: "button", class: "link-button", onclick: () => {
      d.overrides.push({ paths: [], rules: {} });
      renderRules();
    } }, "+ Add folder override"));
}

function overrideCard(override, index, options) {
  const settings = [];
  for (const [rule, keys] of Object.entries(override.rules)) {
    for (const [key, value] of Object.entries(keys)) settings.push({ key: `${rule}.${key}`, value });
  }
  const commit = () => {
    const rules = {};
    for (const s of settings) {
      const [rule, key] = s.key.split(".");
      (rules[rule] ||= {})[key] = s.value;
    }
    override.rules = rules;
    changed();
  };
  const list = el("div", { class: "rule-fields" });
  const draw = () => {
    list.replaceChildren(...settings.map((s, i) => settingRow(s, options, () => { settings.splice(i, 1); draw(); commit(); }, commit)),
      el("button", { type: "button", class: "link-button", onclick: () => {
        settings.push({ key: options[0].key, value: "error" });
        draw(); commit();
      } }, "+ Add setting"));
  };
  draw();
  const pathsId = `o-${index}`;
  return el("article", { class: "card override" },
    el("div", { class: "override-head" },
      el("div", { class: "field" },
        el("label", { for: pathsId }, "Folders or files"),
        el("input", { type: "text", id: pathsId, value: override.paths.join(", "),
          placeholder: "characters/, props/hero_*", spellcheck: false,
          oninput: (e) => { override.paths = e.target.value.split(",").map((p) => p.trim()).filter(Boolean); changed(); } })),
      el("button", { type: "button", class: "secondary", onclick: () => {
        editor.draft.overrides.splice(index, 1);
        renderRules();
      } }, "Remove")),
    list);
}

function settingRow(setting, options, onRemove, onChange) {
  const option = options.find((o) => o.key === setting.key) || options[0];
  const valueBox = el("div");
  const drawValue = (kind) => {
    valueBox.replaceChildren(kind === "severity"
      ? severityControl(setting.value, (v) => { setting.value = v; drawValue(kind); onChange(); })
      : valueInput(kind, setting.value, (v) => { setting.value = v; onChange(); }, { label: "On" }));
  };
  const select = el("select", { "aria-label": "Setting", onchange: (e) => {
    setting.key = e.target.value;
    const kind = options.find((o) => o.key === setting.key).kind;
    setting.value = kind === "severity" ? "error" : kind === "bool" ? true : null;
    drawValue(kind); onChange();
  } }, options.map((o) => el("option", { value: o.key, selected: o.key === option.key }, o.label)));
  drawValue(option.kind);
  return el("div", { class: "override setting-row" }, select, valueBox,
    el("button", { type: "button", class: "icon-button", title: "Remove setting", "aria-label": "Remove setting", onclick: onRemove }, icon("close")));
}

function excludeSection(d) {
  return el("section", {},
    el("h2", {}, "Ignored paths"),
    el("p", { class: "section-help" }, "One pattern per line. A pattern ending in / skips that whole folder; * matches anything."),
    el("div", { class: "field exclude" },
      el("textarea", { "aria-label": "Ignored paths", spellcheck: false, placeholder: "build/\n*_backup.*",
        value: (d.exclude || []).join("\n"),
        oninput: (e) => { d.exclude = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean); changed(); } })));
}
