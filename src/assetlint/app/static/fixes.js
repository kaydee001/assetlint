// The Fix dialog: shows what a fix will change, and applies it. Uses the helpers in app.js.
// The server plans every fix; this page only shows the plan and says which one to apply.
"use strict";

const fixer = { path: null, timer: null, asked: 0 };

// The "Fix…" button on a file card, for files the server says it can fix.
function fixButton(path) {
  if (!state.data.fixable?.includes(path)) return null;
  return el("button", {
    type: "button", class: "secondary fix-button", onclick: () => openFixes(path),
  }, "Fix…");
}

async function openFixes(path) {
  fixer.path = path;
  const dialog = $("fix-dialog");
  dialog.replaceChildren(dialogHead(path), el("p", { class: "fix-loading" }, "Working out the fixes…"));
  if (!dialog.open) dialog.showModal();
  try {
    const rules = [...new Set(state.data.findings.filter((f) => f.path === path).map((f) => f.rule))];
    const { fixes } = await api("/api/fixes", { folder: state.data.folder, path, rules });
    dialog.replaceChildren(dialogHead(path),
      ...(fixes.length
        ? fixes.map(fixSection)
        : [el("p", { class: "fix-loading" }, "Nothing here can be fixed automatically any more. Check the folder again.")]));
    dialog.querySelector("input, .fix button:not(:disabled)")?.focus();
  } catch (error) {
    dialog.replaceChildren(dialogHead(path), el("p", { class: "fix-blocked" }, error.message));
  }
}

function dialogHead(path) {
  return el("header", { class: "fix-head" },
    el("h2", {}, "Fix ", el("code", {}, path)),
    el("button", {
      type: "button", class: "icon-button", "aria-label": "Close", onclick: () => $("fix-dialog").close(),
    }, icon("close")));
}

function fixSection(fix) {
  const section = el("section", { class: "fix" });
  let current = fix;
  const body = el("div");
  const apply = el("button", { type: "button" }, "Apply");
  const show = (f) => {
    current = f;
    const notes = f.notes.map((n) => el("p", { class: "fix-note" }, n));
    const blocked = f.blocked ? [el("p", { class: "fix-blocked" }, f.blocked)] : [];
    body.replaceChildren(changeList(f), ...notes, ...blocked);
    apply.disabled = Boolean(f.blocked);
    apply.textContent = f.button;
  };

  apply.addEventListener("click", async () => {
    apply.disabled = true;
    try {
      const done = await api("/api/fix", {
        folder: state.data.folder, path: fixer.path, fix: current.id,
        fingerprint: current.fingerprint, name: current.name,
      });
      $("fix-dialog").close();
      await check(state.data.folder);
      // Say what the fix did and what's left: the progress is the reward.
      const left = state.data ? state.data.errors + state.data.warnings : null;
      toast(left === null ? done.done
        : left === 0 ? `${done.done}. Nothing left to fix.`
        : `${done.done}. ${plural(left, "problem")} left.`);
    } catch (error) {
      body.append(el("p", { class: "fix-blocked" }, error.message));
      apply.disabled = false;
    }
  });

  const parts = [el("h3", {}, fix.id === "rename" ? "Rename" : fix.title)];
  if (fix.id === "rename") {
    const input = el("input", {
      type: "text", value: fix.name, spellcheck: false, "aria-label": "New name",
      oninput: () => {
        apply.disabled = true;
        clearTimeout(fixer.timer);
        fixer.timer = setTimeout(() => replan(input.value, show), 250);
      },
      onkeydown: (e) => { if (e.key === "Enter" && !apply.disabled) apply.click(); },
    });
    parts.push(el("label", { class: "fix-name" }, "New name", input));
  }
  show(fix);
  section.append(...parts, body, el("div", { class: "fix-actions" }, apply));
  return section;
}

async function replan(name, show) {
  const asked = ++fixer.asked; // only the answer to the latest name counts
  try {
    const { fixes } = await api("/api/fixes", {
      folder: state.data.folder, path: fixer.path, name, rules: ["naming"],
    });
    const rename = fixes.find((f) => f.id === "rename");
    if (rename && asked === fixer.asked) show(rename);
  } catch (error) {
    toast(error.message);
  }
}

function changeList(fix) {
  const label = { rename: "Rename", edit: "Edit", trash: "Trash" };
  return el("ul", { class: "changes" }, fix.changes.map((c) =>
    el("li", {},
      el("span", { class: `change ${c.kind}` }, label[c.kind]),
      el("span", { class: "what" },
        c.kind === "rename" ? [el("code", {}, c.path), " → ", el("code", {}, c.to)]
          : c.kind === "edit" ? [el("code", {}, c.path), el("span", { class: "detail" }, c.detail)]
          : el("code", {}, c.path)))));
}
