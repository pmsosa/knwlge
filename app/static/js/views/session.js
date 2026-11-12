import { $, $$, act, api, el, html, raw, toast, hours, KIND_LABEL } from "../util.js";
import { QUIZ_WIDGETS, readingSwitch, wireReadingSwitch } from "../readingmode.js";
import { icon, KIND_ICON } from "../icons.js";
import { md } from "../md.js";
import { renderItem } from "../items.js";
import { mountTutor } from "../tutor.js";
import { sectionMenus } from "../sectionmenu.js";
import { renderMedia } from "../media.js";

const busy = (m) => m.status === "pending" || m.status === "working";

export default async function session(view, scope, id) {
  let s = await api(`/api/sessions/${id}`);
  let editing = false;
  const draw = () => {
    const top = $("#pane", view)?.scrollTop || 0;   // redraws keep the reader's place
    if (s.state === "ready") drawReady(view, s, editing, (on) => { editing = on; draw(); }, reload);
    else drawWaiting(view, s);
    const pane = $("#pane", view);
    if (pane && top) pane.scrollTop = top;
  };
  let watching = false;
  // sections Gemini is rewriting swap in by themselves
  const watchRevisions = () => {
    if (watching || !(s.revising || []).length) return;
    watching = true;
    scope.every(4000, async () => {
      const fresh = await api(`/api/sessions/${id}`);
      const done = JSON.stringify(fresh.revising) !== JSON.stringify(s.revising) || fresh.warnings.length !== s.warnings.length;
      if (done) { s = fresh; draw(); }
      watching = (s.revising || []).length > 0;
      return watching;
    });
  };
  async function reload() {
    s = await api(`/api/sessions/${id}`);
    draw();
    watchRevisions();
  }
  draw();
  watchRevisions();
  if (s.state !== "ready") {
    scope.every(4000, async () => {
      s = await api(`/api/sessions/${id}`);
      draw();
      if (s.state === "ready") watchMedia(view, scope, s, () => editing);
      return s.state !== "ready";
    });
  } else {
    watchMedia(view, scope, s, () => editing);
  }
}

// Pictures, recordings and illustrations are fetched in the background: swap each one in when it's ready.
function watchMedia(view, scope, s, editing) {
  if (!s.media.some(busy)) return;
  scope.every(4000, async () => {
    const fresh = await api(`/api/sessions/${s.id}`);
    for (const m of fresh.media) {
      const old = s.media.find((x) => x.id === m.id);
      if (old && old.status !== m.status) {
        view.querySelector(`[data-media="${CSS.escape(m.id)}"]`)?.replaceWith(renderMedia(m, { editing: editing() }));
      }
    }
    s.media = fresh.media;
    return s.media.some(busy);
  });
}

function crumbs(s) {
  return html`<p class="crumbs"><a href="#/course/${s.course_id}">${s.course_title}</a> › Session ${s.seq} of ${s.total}</p>`;
}

const STATE = { pending: "waiting", writing: "writing…", checking: "checking…", failed: "failed" };

// Two panes: the course outline stays put on the left, the session scrolls on the right.
function frame(view, s, inner) {
  view.classList.add("fill");
  view.innerHTML = html`<div class="split">
    <aside class="side">
      <p class="crumbs"><a href="#/course/${s.course_id}">← Course</a></p>
      <h2 style="margin-bottom:4px">${s.course_title}</h2>
      <div class="small muted">${s.outline.filter((o) => o.done).length} of ${s.outline.length} sessions done</div>
      <ol class="outline">${s.outline.map((o) => raw(html`<li><a href="#/session/${o.id}"
        class="${o.id === s.id ? "here" : ""} ${o.state !== "ready" && o.id !== s.id ? "off" : ""}" ${raw(o.id === s.id ? 'aria-current="page"' : "")}>
        <span class="num ${o.done ? "done" : o.kind !== "lesson" ? "special" : ""}">${o.done ? "✓" : o.seq}</span>
        <span>${o.title}${raw(o.state !== "ready" ? html` <span class="faint small">(${STATE[o.state] || o.state})</span>` : "")}</span></a></li>`))}</ol>
    </aside>
    <section class="pane" id="pane">${raw(inner)}</section></div>`;
  view.querySelector(".outline a.here")?.scrollIntoView({ block: "nearest" });
}

function drawWaiting(view, s) {
  frame(view, s, html`${raw(crumbs(s))}<h1>${s.title}</h1>
    <div class="panel">${raw(s.state === "failed"
      ? html`<div class="note bad">Writing this session failed: ${s.error || "unknown error"}. Use “Try again” on the course page.</div>`
      : html`<p class="row" style="margin:0"><span class="spinner"></span> <b>${s.state === "checking" ? "Double-checking this session…" : "Writing this session…"}</b></p>
        <p class="small muted" style="margin:.4rem 0 0">It'll appear here by itself in a minute or two.</p>`)}</div>`);
}

function drawReady(view, s, editing, setEditing, reload) {
  const ctx = { courseId: s.course_id, editing, onChange: () => refreshProgress(view, s) };
  const content = s.content || {};
  const items = s.items;
  const bySection = (sec) => items.filter((i) => i.section === sec);
  const isProject = s.kind === "project";
  const rm = !!s.reading_mode;   // Reading mode: questions, practice, written work and warm-ups are hidden for this person

  frame(view, s, html`${raw(crumbs(s))}
    <div class="spread"><h1 style="margin:0">${s.title}</h1>
      <span class="row"><span class="pill ${s.kind === "lesson" ? "" : "teal"}">${s.kind_label}</span><span class="pill">${raw(icon("clock", 12))}about ${hours(s.minutes)}</span>
      ${raw(s.done ? `<span class="pill good">${icon("check", 12)}Finished</span>` : "")}</span></div>
    ${raw(content.goal ? html`<p class="goal" style="margin-top:.8rem"><b>${content.goal}</b></p>` : "")}
    ${raw(content.hook ? html`<p class="muted">${raw(md(content.hook, { inline: true }))}</p>` : "")}
    ${raw(s.objectives.length ? html`<ul class="small muted">${s.objectives.map((o) => raw(html`<li>${o}</li>`))}</ul>` : "")}
    <div class="row" style="margin:.6rem 0 0" id="tools">
      ${raw(readingSwitch(rm, { compact: true }))}
      ${raw(s.can_edit && !rm ? html`<button class="ghost small" data-act="edit">${raw(icon(editing ? "check" : "pencil", 14))}${editing ? "Done editing questions" : "Edit questions"}</button>
      <button class="ghost small" data-act="rewrite">${raw(icon("refresh-cw", 14))}Rewrite whole session</button>` : "")}
      ${raw(s.can_edit && rm ? html`<button class="ghost small" data-act="rewrite">${raw(icon("refresh-cw", 14))}Rewrite whole session</button>` : "")}
      <span class="small faint" id="prog"></span>
    </div>
    ${raw(s.can_edit && !isProject ? `<p class="small faint tip-mouse" style="margin:6px 0 0">Tip: right-click a section (or select some text in it first) to edit it, rewrite it with Gemini or add to it.</p>
      <p class="small faint tip-touch" style="margin:6px 0 0">Tip: tap ${icon("ellipsis", 14)} beside a section's title to edit it, rewrite it with Gemini or add to it.</p>` : "")}
    ${raw(s.warnings.length ? html`<details class="note warn small" style="margin-top:1rem"><summary style="cursor:pointer">The second read-through flagged ${s.warnings.length} thing${s.warnings.length > 1 ? "s" : ""} to double-check</summary>
      <ul>${s.warnings.map((w) => raw(html`<li>${w}</li>`))}</ul></details>` : "")}
    <div id="body"></div>`);
  const body = $("#body", view);

  if (s.warmup.length) {
    body.append(el(html`<h2 class="section-title">Warm-up <span class="pill teal">from earlier sessions</span></h2>`));
    body.append(el(`<p class="muted small">A few questions from memory first. Recalling is what makes it stick.</p>`));
    for (const w of s.warmup) body.append(renderItem(w, { ...ctx, warmup: true, editing: false }));
  }

  if (isProject) {
    body.append(el(html`<div class="prose" style="margin-top:1.5rem">${raw(md(content.intro_markdown || ""))}</div>`));
    const opts = bySection("project");
    if (rm) {
      body.append(el(html`<div class="note" style="margin-top:1rem">This session is a hands-on project${raw(opts.length ? html` (${opts.map((o) => o.title).filter(Boolean).join(", ")})` : "")}.
        Turn off Reading mode to pick one and get feedback on what you make.</div>`));
    }
    if (!rm) body.append(el(html`<h2 class="section-title">Pick a project</h2>`));
    const tabs = rm ? el("<div></div>") : el(html`<div class="options-tabs">${opts.map((o, i) => raw(html`<button class="${i ? "ghost" : ""} small" data-opt="${i}">${o.title || `Option ${i + 1}`}</button>`))}</div>`);
    body.append(tabs);
    const holder = el(`<div></div>`);
    body.append(holder);
    const started = Math.max(0, opts.findIndex((o) => o.last));
    const show = (i) => {
      $$("[data-opt]", tabs).forEach((b, k) => b.classList.toggle("ghost", k !== i));
      holder.replaceChildren(renderItem(opts[i], ctx));
    };
    $$("[data-opt]", tabs).forEach((b) => b.addEventListener("click", () => show(Number(b.dataset.opt))));
    if (opts.length && !rm) show(started);
    if (content.tips_markdown) body.append(el(html`<details class="example"><summary>Tips and pitfalls</summary><div class="prose">${raw(md(content.tips_markdown))}</div></details>`));
  } else {
    (content.chunks || []).forEach((ch, i) => {
      const busyHere = (s.revising || []).includes(i);
      const block = el(html`<section class="chunk ${busyHere ? "revising" : ""}" data-chunk="${i}"><h2 class="section-title">${ch.title}
          ${raw(s.can_edit && !busyHere ? html`<button class="chunk-menu" type="button" data-chunk-menu aria-label="Section options for ${ch.title}" title="Edit, rewrite or add">${raw(icon("ellipsis", 18))}</button>` : "")}</h2>
        ${raw(busyHere ? `<div class="revising-note small"><span class="spinner"></span> Gemini is rewriting this section. It'll swap in by itself.</div>` : "")}
        <div class="prose">${raw(md(ch.markdown))}</div>
        <div class="chunk-media"></div>
        ${raw(ch.example_markdown ? html`<details class="example" open><summary>Worked example</summary><div class="prose">${raw(md(ch.example_markdown))}</div></details>` : "")}
      </section>`);
      const mediaBox = block.querySelector(".chunk-media");
      const shown = s.media.filter((x) => x.chunk === i && !(rm && x.kind === "widget" && QUIZ_WIDGETS.has(x.spec?.type)));
      for (const m of shown) mediaBox.append(renderMedia(m, { editing }));
      if (!rm) for (const q of items.filter((it) => it.section === "check" && it.chunk === i)) block.append(renderItem(q, ctx));
      body.append(block);
    });
    const practice = rm ? [] : bySection("practice");
    if (practice.length) {
      body.append(el(html`<h2 class="section-title">Practice <span class="pill">${practice.length}</span></h2>`));
      for (const q of practice) body.append(renderItem(q, ctx));
    }
    const ex = rm ? [] : bySection("exercise");
    if (ex.length) {
      body.append(el(html`<h2 class="section-title">${ex.length > 1 ? "Written exercises" : "Written exercise"}</h2>`));
      body.append(el(`<p class="muted small">Gemini gives feedback against the rubric. Try as many times as you like.</p>`));
      for (const q of ex) body.append(renderItem(q, ctx));
    }
  }

  const further = s.reading.filter((r) => r.kind !== "source");
  const sources = s.reading.filter((r) => r.kind === "source");
  if (further.length) {
    body.append(el(html`<h2 class="section-title">Going further <span class="pill">optional</span></h2>`));
    body.append(el(html`<ul class="reading">${further.map((r) => raw(html`<li><span class="kind">${raw(icon(KIND_ICON[r.kind] || "link", 13))}${KIND_LABEL[r.kind] || "Link"}</span><div>
      <div class="t">${raw(r.url ? html`<a href="${r.url}" target="_blank" rel="noopener noreferrer">${r.title}</a>` : html`${r.title}`)}</div>
      <div class="small muted">${[r.creator, r.kind, r.minutes ? hours(r.minutes) : "", r.free ? "free" : "paid"].filter(Boolean).join(" · ")}</div>
      <div class="small">${r.why}</div></div></li>`))}</ul>`));
  }

  if (sources.length) {
    body.append(el(html`<details class="small" style="margin-top:18px"><summary><b>Sources Gemini looked at</b>
      <span class="muted">(live research)</span></summary><ul style="margin:6px 0 0;padding-left:1.2em">${sources.map((r) =>
        raw(html`<li><a href="${r.url}" target="_blank" rel="noopener noreferrer">${r.title}</a>${raw(r.creator ? html` <span class="faint">· ${r.creator}</span>` : "")}</li>`))}</ul></details>`));
  }

  body.append(wrapup(s, content, isProject));
  body.append(el(html`<details class="panel" style="margin-top:1rem"><summary style="cursor:pointer"><b>My notes</b> <span class="small muted">(saved when you click away)</span></summary>
    <textarea id="note" style="margin-top:.7rem" placeholder="Anything you want to remember.">${s.note}</textarea></details>`));
  $("#note", view).addEventListener("change", (e) => api(`/api/sessions/${s.id}/note`, { method: "PUT", json: { text: e.target.value } })
    .then(() => toast("Note saved.")).catch((err) => toast(err.message, true)));

  body.append(el(html`<nav class="pager">
    ${raw(s.prev ? html`<a href="#/session/${s.prev.id}"><small>${raw(icon("chevron-left", 13))}Previous</small>${s.prev.title}</a>` : "<span></span>")}
    ${raw(s.next ? html`<a class="right" href="#/session/${s.next.id}"><small>Next${raw(icon("chevron-right", 13))}</small>${s.next.title}</a>` : "")}
  </nav>`));

  wireReadingSwitch($("#tools", view), s.course_id, () => reload());
  if (!isProject) sectionMenus(body, s, reload);
  mountTutor(s.course_id, s.id, "this session");
  $('[data-act="edit"]', view)?.addEventListener("click", () => setEditing(!editing));
  $('[data-act="rewrite"]', view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    const wish = prompt("Rewrite the whole session from scratch. Anything you'd like different? (Your answers here will be cleared.)", "");
    if (wish === null) return;
    await api(`/api/sessions/${s.id}/regenerate`, { method: "POST", json: { text: wish } });
    toast("Rewriting. It'll be back in a minute or two.");
    location.hash = `#/course/${s.course_id}`;
  }));
  refreshProgress(view, s);
}

function wrapup(s, content, isProject) {
  const w = content.wrapup || { key_points: [], teaser: "" };
  if (s.reading_mode) return readingWrapup(s, w);
  const box = el(html`<div class="panel wrapup" style="margin-top:2.2rem">
    <h2>${isProject ? "When you're done" : "Wrap-up"}</h2>
    <p class="muted">${isProject ? "A few sentences on what you made and what you learned making it." : "In two or three sentences, from memory: what did you learn?"}</p>
    <textarea id="summary" placeholder="Writing it down is the last step that makes it stick.">${s.summary_note}</textarea>
    <div class="row" style="margin-top:.6rem">
      ${raw(w.key_points.length ? `<button class="ghost" data-act="compare">Compare with the key points</button>` : "")}
      <button data-act="finish">${raw(icon("check", 15))}${s.done ? "Save" : "Finish session"}</button>
      ${raw(s.done ? `<button class="link small" data-act="reopen">Mark as not finished</button>` : "")}
    </div>
    <div class="keys" hidden><p style="margin:1rem 0 .3rem"><b>Key points</b></p>
      <ul>${w.key_points.map((k) => raw(html`<li>${raw(md(k, { inline: true }))}</li>`))}</ul>
      ${raw(w.teaser ? html`<p class="muted"><b>Next time:</b> ${w.teaser}</p>` : "")}</div>
  </div>`);
  box.querySelector('[data-act="compare"]')?.addEventListener("click", () => { box.querySelector(".keys").hidden = false; });
  box.querySelector('[data-act="finish"]').addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/sessions/${s.id}/finish`, { method: "POST", json: { summary: box.querySelector("#summary").value } });
    box.querySelector(".keys").hidden = false;
    if (s.done) return toast("Saved.");
    toast(s.next ? "Nice work. On to the next one whenever you like." : "That's the whole course. Well done!");
    s.done = true;
    if (s.next) setTimeout(() => { location.hash = `#/session/${s.next.id}`; }, 1200);
  }));
  box.querySelector('[data-act="reopen"]')?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/sessions/${s.id}/reopen`, { method: "POST" });
    location.reload();
  }));
  return box;
}

function readingWrapup(s, w) {
  const box = el(html`<div class="panel wrapup" style="margin-top:2.2rem">
    <h2>Key points</h2>
    ${raw(w.key_points.length ? html`<ul>${w.key_points.map((k) => raw(html`<li>${raw(md(k, { inline: true }))}</li>`))}</ul>` : "")}
    ${raw(w.teaser ? html`<p class="muted"><b>Next time:</b> ${w.teaser}</p>` : "")}
    <div class="row" style="margin-top:.6rem">
      ${raw(s.done ? `<span class="small muted">${icon("check", 14)} Read</span><button class="link small" data-act="reopen">Mark as not read</button>`
        : `<button data-act="finish">${icon("check", 15)}Mark as read</button>`)}
    </div>
  </div>`);
  box.querySelector('[data-act="finish"]')?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/sessions/${s.id}/finish`, { method: "POST", json: { summary: s.summary_note || "" } });
    toast(s.next ? "Marked as read. On to the next one whenever you like." : "That's the whole course read. Well done!");
    s.done = true;
    if (s.next) setTimeout(() => { location.hash = `#/session/${s.next.id}`; }, 1200);
    else box.querySelector(".row").innerHTML = `<span class="small muted">${icon("check", 14)} Read</span>`;
  }));
  box.querySelector('[data-act="reopen"]')?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/sessions/${s.id}/reopen`, { method: "POST" });
    location.reload();
  }));
  return box;
}

async function refreshProgress(view, s) {
  try {
    if (s.reading_mode) { const box = $("#prog", view); if (box) box.textContent = ""; return; }
    const p = s.progress = (await api(`/api/sessions/${s.id}`)).progress;
    const bits = [];
    if (p.questions) bits.push(`${p.tried} of ${p.questions} questions answered`);
    if (p.written) bits.push(`${p.written_done} of ${p.written} written ${p.written > 1 ? "pieces" : "piece"} sent`);
    const box = $("#prog", view);
    if (box) box.textContent = bits.join(" · ");
  } catch { /* fine */ }
}
