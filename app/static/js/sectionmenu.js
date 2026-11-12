// Right-click a part of a lesson (or select some text in it first) for a small menu: edit it by hand, have Gemini
// rewrite it or add to it, ask the tutor about it, or copy. Shift + right-click still opens the browser's own menu.
// Editors also get a "⋯" button on each part's heading, for touch screens.
import { act, api, el, html, raw, toast } from "./util.js";
import { icon } from "./icons.js";
import { md } from "./md.js";
import { openChat } from "./tutor.js";

/** Wire the menu onto a rendered session. `s` is the session from the API; `reload()` redraws it from the server. */
export function sectionMenus(root, s, reload) {
  let touch = false;   // a long-press on a phone also fires "contextmenu": leave that to the phone (text selection)
  root.addEventListener("pointerdown", (e) => { touch = e.pointerType === "touch"; });
  root.addEventListener("contextmenu", (e) => {
    if (e.shiftKey || touch) return;
    const block = e.target.closest(".chunk[data-chunk]");
    if (!block || e.target.closest("input, textarea, select, button, .q, iframe, audio, video")) return;
    if (block.classList.contains("revising")) return;
    e.preventDefault();
    showMenu({ x: e.clientX, y: e.clientY }, block, s, reload, selectionIn(block));
  });
  root.querySelectorAll("[data-chunk-menu]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const r = b.getBoundingClientRect();
    const block = b.closest(".chunk");
    showMenu({ x: r.left, y: r.bottom + 4 }, block, s, reload, selectionIn(block));
  }));
}

function selectionIn(block) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return "";
  const r = sel.getRangeAt(0);
  if (!block.contains(r.commonAncestorContainer)) return "";
  return sel.toString().trim().slice(0, 4000);
}

function closeMenu() {
  document.querySelector(".ctx-menu")?.remove();
  document.removeEventListener("pointerdown", outside, true);
  window.removeEventListener("blur", closeMenu);
  document.querySelector("#pane")?.removeEventListener("scroll", closeMenu);
}
function outside(e) { if (!e.target.closest(".ctx-menu")) closeMenu(); }

function showMenu(at, block, s, reload, picked) {
  closeMenu();
  const i = Number(block.dataset.chunk);
  const ch = s.content.chunks[i];
  const short = picked ? `“${picked.length > 40 ? picked.slice(0, 40).trim() + "…" : picked}”` : "";
  const entries = [];
  if (s.can_edit) {
    entries.push(["edit", "Edit section", "the Markdown, by hand", "pencil"]);
    entries.push(["rewrite", picked ? "Rewrite the selection" : "Rewrite with Gemini", "say what should change", "sparkles"]);
    entries.push(["add", "Add to this section", picked ? "right after the selection" : "say what you'd like to see", "plus"]);
    entries.push(null);
  }
  entries.push(["ask", picked ? "Ask the tutor about this" : "Ask the tutor about this section", picked ? short : "", "message-circle-question"]);
  if (picked) entries.push(["copy", "Copy", "", "copy"]);
  const menu = el(html`<div class="ctx-menu" role="menu" aria-label="${ch.title}">
    <div class="ctx-head small faint">${ch.title}</div>
    ${raw(entries.map((x) => (x ? html`<button type="button" role="menuitem" data-do="${x[0]}">${raw(icon(x[3], 16))}<span class="ctx-label"><span>${x[1]}</span>${raw(x[2] ? html`<small>${x[2]}</small>` : "")}</span></button>`
      : `<hr>`)).join(""))}
    <div class="ctx-foot small faint">Shift + right-click for the browser's menu</div></div>`);
  document.body.append(menu);
  const { innerWidth: W, innerHeight: H } = window;
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(at.x, W - r.width - 8))}px`;
  menu.style.top = `${Math.max(8, at.y + r.height > H - 8 ? at.y - r.height : at.y)}px`;
  const items = [...menu.querySelectorAll("[role=menuitem]")];
  items[0]?.focus();
  menu.addEventListener("keydown", (e) => {
    const k = items.indexOf(document.activeElement);
    if (e.key === "Escape") { closeMenu(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(k + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(k - 1 + items.length) % items.length].focus(); }
  });
  setTimeout(() => {
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("blur", closeMenu);
    document.querySelector("#pane")?.addEventListener("scroll", closeMenu, { once: true });
  });
  menu.addEventListener("click", (e) => {
    const b = e.target.closest("[data-do]");
    if (!b) return;
    closeMenu();
    const what = b.dataset.do;
    if (what === "edit") editDialog(s, i, ch, picked, reload);
    else if (what === "rewrite" || what === "add") reviseDialog(s, i, ch, what, picked, block, reload);
    else if (what === "ask") {
      openChat(s.course_id, s.id, "this session", picked || ch.title, !picked);
    } else if (what === "copy") copy(picked);
  });
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied."); }
  catch { toast("Your browser didn't allow copying. Use Ctrl+C.", true); }
}

// ---------- dialogs ----------

function dialog(markup) {
  const d = el(markup);
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });   // click on the backdrop
  d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  d.showModal();
  return d;
}

function editDialog(s, i, ch, picked, reload) {
  const d = dialog(html`<dialog class="modal wide" aria-label="Edit section">
    <form method="dialog" class="modal-body">
      <div class="spread"><h2 style="margin:0">Edit section <span class="tone2">in Markdown.</span></h2>
        <div class="seg" role="tablist"><button type="button" class="on" data-view="write">${raw(icon("pencil", 14))}write</button><button type="button" data-view="preview">${raw(icon("book-open", 14))}preview</button></div></div>
      <label class="field" for="ed-title">Title</label><input type="text" id="ed-title" value="${ch.title}">
      <div class="ed-write">
        <label class="field" for="ed-md">Lesson <span class="faint small">Markdown · $maths$ · \`\`\`code\`\`\`</span></label>
        <textarea id="ed-md" class="mono" spellcheck="true">${ch.markdown}</textarea>
        <label class="field" for="ed-ex">Worked example <span class="faint small">(optional)</span></label>
        <textarea id="ed-ex" class="mono short">${ch.example_markdown || ""}</textarea>
      </div>
      <div class="ed-preview prose" hidden></div>
      <div class="row modal-actions"><span class="small faint">Your learners' answers aren't touched.</span><span style="flex:1"></span>
        <button type="button" class="ghost" data-close>cancel</button><button type="button" data-act="save">${raw(icon("check", 15))}save</button></div>
    </form></dialog>`);
  const ta = d.querySelector("#ed-md");
  // put the cursor on what was selected, when it can be found in the Markdown
  if (picked) {
    const first = picked.split("\n")[0].trim().slice(0, 60);
    const at = first ? ta.value.indexOf(first) : -1;
    if (at >= 0) { ta.focus(); ta.setSelectionRange(at, at + first.length); scrollToCaret(ta); }
  } else ta.focus();
  d.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    const prev = b.dataset.view === "preview";
    d.querySelectorAll("[data-view]").forEach((x) => x.classList.toggle("on", x === b));
    d.querySelector(".ed-write").hidden = prev;
    const out = d.querySelector(".ed-preview");
    out.hidden = !prev;
    if (prev) out.innerHTML = md(ta.value) + (d.querySelector("#ed-ex").value.trim()
      ? html`<details class="example" open><summary>Worked example</summary><div class="prose">${raw(md(d.querySelector("#ed-ex").value))}</div></details>` : "");
  }));
  d.querySelector('[data-act="save"]').addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/sessions/${s.id}/chunks/${i}`, { method: "PUT", json: {
      title: d.querySelector("#ed-title").value, markdown: ta.value, example_markdown: d.querySelector("#ed-ex").value } });
    d.close();
    toast("Saved.");
    await reload();
  }));
}

function scrollToCaret(ta) {
  const line = ta.value.slice(0, ta.selectionStart).split("\n").length;
  ta.scrollTop = Math.max(0, (line - 3) * parseFloat(getComputedStyle(ta).lineHeight || "20"));
}

const COPY = {
  rewrite: { title: "Rewrite", tone: "with Gemini.", label: "What should change?",
    hint: "e.g. simpler words, a sports analogy, shorter, more on why it works, fix the second paragraph",
    go: "rewrite", toast: "Rewriting this section. It'll swap in by itself in a minute." },
  add: { title: "Add", tone: "to this section.", label: "What would you like to add or see here?",
    hint: "e.g. a table comparing the three, a real-world example, a short history, a common mistake to watch for",
    go: "add it", toast: "Adding to this section. It'll swap in by itself in a minute." },
};

function reviseDialog(s, i, ch, mode, picked, block, reload) {
  const t = COPY[mode];
  const d = dialog(html`<dialog class="modal" aria-label="${t.title} section">
    <form class="modal-body">
      <h2 style="margin:0">${t.title} <span class="tone2">${t.tone}</span></h2>
      <p class="small muted" style="margin:4px 0 0">Section: <b>${ch.title}</b>. Only this section changes; the rest of the session stays as it is.</p>
      ${raw(picked ? html`<div><label class="field">${mode === "add" ? "Added right after" : "About this passage"}</label>
        <blockquote class="picked">${picked}</blockquote></div>` : "")}
      <div><label class="field" for="rv-wish">${t.label}</label>
        <textarea id="rv-wish" required placeholder="${t.hint}"></textarea></div>
      <div class="row modal-actions"><span class="small faint">Uses a Gemini call. Ctrl+Enter sends.</span><span style="flex:1"></span>
        <button type="button" class="ghost" data-close>cancel</button><button type="submit">${raw(icon(mode === "add" ? "plus" : "sparkles", 15))}${t.go}</button></div>
    </form></dialog>`);
  const ta = d.querySelector("#rv-wish");
  ta.focus();
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) d.querySelector("form").requestSubmit(); });
  d.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    act(d.querySelector('button[type="submit"]'), async () => {
      await api(`/api/sessions/${s.id}/chunks/${i}/revise`, { method: "POST", json: { mode, wish: ta.value, focus: picked } });
      d.close();
      toast(t.toast);
      await reload();
    });
  });
}

