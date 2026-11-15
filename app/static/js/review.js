// Drafts, history and flags: the review dialog (before and after, accept or discard), the version list with restore,
// the flag dialog for learners, and the course page's Changes and Flags tabs.
import { $, $$, act, ago, api, el, esc, html, raw, toast } from "./util.js";
import { icon } from "./icons.js";
import { md } from "./md.js";

// ---------- a word-level diff ----------

/** Markup showing what changed from `a` to `b`, word by word (<del> and <ins>). Falls back to two blocks when huge. */
export function wordDiff(a, b) {
  a = String(a ?? ""); b = String(b ?? "");
  if (a === b) return esc(a);
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
  if (A.length * B.length > 4_000_000) return html`<del class="block">${a}</del><ins class="block">${b}</ins>`;
  // trim the common start and end, then a classic LCS table on the middle
  let s = 0;
  while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let e = 0;
  while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
  const a2 = A.slice(s, A.length - e), b2 = B.slice(s, B.length - e);
  const n = a2.length, m = b2.length;
  const L = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
    L[i][j] = a2[i] === b2[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  }
  const out = [esc(A.slice(0, s).join(""))];
  let i = 0, j = 0, del = "", ins = "";
  const flush = () => {
    if (del) out.push(`<del>${esc(del)}</del>`);
    if (ins) out.push(`<ins>${esc(ins)}</ins>`);
    del = ""; ins = "";
  };
  while (i < n && j < m) {
    if (a2[i] === b2[j]) { flush(); out.push(esc(a2[i])); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) del += a2[i++];
    else ins += b2[j++];
  }
  while (i < n) del += a2[i++];
  while (j < m) ins += b2[j++];
  flush();
  out.push(esc(A.slice(A.length - e).join("")));
  return out.join("");
}

// ---------- dialogs ----------

export function dialog(markup) {
  const d = el(markup);
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  d.showModal();
  return d;
}

const FIELD = { title: "Title", markdown: "Lesson", example_markdown: "Worked example", prompt: "Question", options: "Options",
  answer: "Answer", explanation: "Explanation", rubric: "Rubric" };

const asText = (k, v) => (k === "options" ? (v || []).join("\n")
  : k === "rubric" ? (v || []).map((r) => `${r.criterion} (${r.points}): ${r.description}`).join("\n") : String(v ?? ""));

function fieldsDiff(before, after, keys) {
  return keys.filter((k) => asText(k, before?.[k]) || asText(k, after?.[k])).map((k) => {
    const a = asText(k, before?.[k]), b = asText(k, after?.[k]);
    return html`<div class="diff-field"><div class="small faint">${FIELD[k]}${a === b ? " · unchanged" : ""}</div>
      <div class="diff">${raw(wordDiff(a, b))}</div></div>`;
  }).join("");
}

function planList(rows) {
  return html`<ol class="plan-diff">${rows.map((r) => raw(html`<li class="${r.removed ? "removed" : r.new ? "added" : ""}">
    <span class="num">${r.removed ? "–" : r.seq}</span><div><b>${r.title}</b>
      ${raw([r.new && `<span class="pill good">new</span>`, r.removed && `<span class="pill bad">removed</span>`,
    r.moved && `<span class="pill">moved</span>`, r.renamed && `<span class="pill">renamed</span>`,
    r.rewrite && `<span class="pill teal">to be rewritten</span>`].filter(Boolean).join(" "))}
      <div class="small muted">${(r.topics || []).join(" · ")}</div></div></li>`))}</ol>`;
}

const STATUS = { working: "The AI is writing it…", pending: "Ready to review", failed: "Didn't work", accepted: "Accepted", discarded: "Discarded" };

function changeBody(ch) {
  if (ch.status === "working") return `<p class="row"><span class="spinner"></span> The AI is writing this draft. It usually takes under a minute.</p>`;
  if (ch.status === "failed") return html`<div class="note bad">${ch.error || "It didn't work."} Discard it and ask again.</div>`;
  if (ch.target === "plan") return planList(ch.after || []);
  if (ch.target === "session") {
    return html`<p class="small muted">Questions: ${ch.before_questions} now → ${ch.after_questions} in the new version. Answers people gave stay in history.</p>
      <div class="seg" role="tablist"><button type="button" class="on" data-view="new">${raw(icon("book-open", 14))}new version</button>
        <button type="button" data-view="diff">${raw(icon("git-compare", 14))}what changed</button></div>
      <div class="v-new prose">${raw(md(ch.after || ""))}</div>
      <div class="v-diff diff" hidden>${raw(wordDiff(ch.before, ch.after))}</div>`;
  }
  const keys = ch.target === "chunk" ? ["title", "markdown", "example_markdown"] : ["prompt", "options", "answer", "explanation", "rubric"];
  return html`<div class="seg" role="tablist"><button type="button" class="on" data-view="diff">${raw(icon("git-compare", 14))}what changed</button>
      <button type="button" data-view="new">${raw(icon("book-open", 14))}new version</button></div>
    <div class="v-diff">${raw(fieldsDiff(ch.before, ch.after, keys))}</div>
    <div class="v-new prose" hidden>${raw(ch.target === "chunk"
    ? `<h3>${esc(ch.after?.title)}</h3>${md(ch.after?.markdown || "")}${ch.after?.example_markdown ? `<h4>Worked example</h4>${md(ch.after.example_markdown)}` : ""}`
    : `${md(ch.after?.prompt || "")}${(ch.after?.options || []).length ? `<ul>${ch.after.options.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}
       <p><b>Answer:</b> ${esc(ch.after?.answer)}</p>${ch.after?.explanation ? `<p class="muted">${esc(ch.after.explanation)}</p>` : ""}`)}</div>`;
}

/** Look at a draft and accept or discard it. Resolves once it's decided (or the dialog is closed). */
export async function openReview(changeId, onDone = () => {}) {
  const ch = await api(`/api/changes/${changeId}`);
  const d = dialog(html`<dialog class="modal wide" aria-label="Review a change">
    <div class="modal-body">
      <div class="spread"><h2 style="margin:0">${ch.where} <span class="tone2">${ch.kind === "ai" ? "rewritten by the AI" : "edited by hand"}</span></h2>
        <span class="pill ${ch.status === "pending" ? "accent" : ""}">${STATUS[ch.status] || ch.status}</span></div>
      <p class="small muted" style="margin:4px 0 0">${ch.by ? `Asked by ${ch.by}` : ""} ${ago(ch.created_at)}${raw(ch.wish ? html`: “${ch.wish}”` : "")}</p>
      ${raw(ch.stale ? `<div class="note warn small">This has changed since the draft was made. Accepting it replaces those newer changes.</div>` : "")}
      ${raw(ch.gone ? `<div class="note bad small">What this draft was for has been replaced since (the session was rewritten). Discard it.</div>` : "")}
      ${raw(ch.notes.length ? html`<ul class="small note">${ch.notes.map((n) => raw(html`<li>${n}</li>`))}</ul>` : "")}
      <div class="review-body">${raw(changeBody(ch))}</div>
      <div class="row modal-actions">
        <span class="small faint">${ch.can_publish ? "Nothing changes for learners until you accept." : "The course's owner or an admin accepts it."}</span>
        <span style="flex:1"></span>
        <button type="button" class="ghost" data-close>close</button>
        ${raw(ch.status !== "accepted" && ch.status !== "discarded" && (ch.by_me || ch.can_publish) ? `<button type="button" class="ghost danger-text" data-act="discard">${icon("x", 15)}discard</button>` : "")}
        ${raw(ch.status === "pending" && ch.can_publish && !ch.gone ? `<button type="button" data-act="accept">${icon("check", 15)}${ch.stale ? "accept anyway" : "accept"}</button>` : "")}
      </div></div></dialog>`);
  $$("[data-view]", d).forEach((b) => b.addEventListener("click", () => {
    $$("[data-view]", d).forEach((x) => x.classList.toggle("on", x === b));
    $(".v-new", d).hidden = b.dataset.view !== "new";
    $(".v-diff", d).hidden = b.dataset.view !== "diff";
  }));
  $('[data-act="accept"]', d)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/changes/${ch.id}/accept`, { method: "POST", json: { force: ch.stale } });
    d.close();
    toast("Accepted. It's live.");
    await onDone("accepted");
  }));
  $('[data-act="discard"]', d)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/changes/${ch.id}/discard`, { method: "POST" });
    d.close();
    toast("Discarded.");
    await onDone("discarded");
  }));
}

// ---------- history ----------

const SOURCE = { original: "As first written", hand: "Edited", ai: "AI rewrite", rollback: "Restored" };

function versionBody(target, data, prev) {
  if (target === "plan") return html`<ol class="small">${(data.sessions || []).map((s) => raw(html`<li>${s}</li>`))}</ol>`;
  if (target === "session") return html`<p class="small">${data.title} · ${data.questions} questions</p><ol class="small">${(data.chunks || []).map((t) => raw(html`<li>${t}</li>`))}</ol>`;
  const keys = target === "chunk" ? ["title", "markdown", "example_markdown"] : ["prompt", "options", "answer", "explanation", "rubric"];
  return fieldsDiff(prev || data, data, keys);
}

/** Every version of a part, question, session or plan; any earlier one can be restored. */
export async function openHistory(target, id, label, onDone = () => {}) {
  const h = await api(`/api/history?target=${encodeURIComponent(target)}&id=${encodeURIComponent(id)}`);
  const v = h.versions;
  const d = dialog(html`<dialog class="modal wide" aria-label="History">
    <div class="modal-body">
      <h2 style="margin:0">History <span class="tone2">of ${label}.</span></h2>
      ${raw(v.length ? "" : `<p class="muted">No changes yet: this is still the version first written.</p>`)}
      <ul class="versions">${v.map((x, k) => raw(html`<li>
        <details><summary><span class="num">${x.n}</span> <b>${SOURCE[x.source] || x.source}</b>
          <span class="small muted">${x.who ? `by ${x.who} ` : ""}${ago(x.at)}${x.why && x.source !== "original" ? ` · ${x.why}` : ""}</span>
          ${raw(x.latest ? `<span class="pill accent">live</span>` : "")}</summary>
          <div class="version-body">${raw(versionBody(target, x.data, target === "chunk" || target === "item" ? v[k + 1]?.data : null))}</div>
          ${raw(!x.latest ? html`<button class="ghost small" data-restore="${x.id}">${raw(icon("rotate-ccw", 14))}${h.can_publish ? "Restore this version" : "Suggest going back to this"}</button>` : "")}
        </details></li>`))}</ul>
      <div class="row modal-actions"><span class="small faint">Versions are kept forever. Restoring one adds a new version; nothing is lost.</span>
        <span style="flex:1"></span><button type="button" class="ghost" data-close>close</button></div></div></dialog>`);
  $$("[data-restore]", d).forEach((b) => b.addEventListener("click", () => act(b, async () => {
    const r = await api(`/api/versions/${b.dataset.restore}/restore`, { method: "POST" });
    d.close();
    toast(r.applied ? "Restored." : "Sent for review: the course's owner or an admin accepts it.");
    await onDone();
  })));
}

// ---------- flags (learners) ----------

const FLAG_WHAT = { chunk: "this part of the lesson", item: "this question or its answer", feedback: "this feedback", reading: "this suggestion" };

export function openFlag(target, targetId, onDone = () => {}) {
  const d = dialog(html`<dialog class="modal" aria-label="Flag a problem">
    <form class="modal-body">
      <h2 style="margin:0">Something wrong <span class="tone2">with ${FLAG_WHAT[target]}?</span></h2>
      <p class="small muted" style="margin:4px 0 0">The AI takes a second look straight away, and the course's authors see it.
        You'll find what happened on your account page.</p>
      <div><label class="field" for="fl-note">What looks wrong? <span class="faint small">(optional, but it helps)</span></label>
        <textarea id="fl-note" maxlength="2000" placeholder="e.g. The answer says 12 but I get 14; the date of the battle is off; this link is broken"></textarea></div>
      <div class="row modal-actions"><span style="flex:1"></span><button type="button" class="ghost" data-close>cancel</button>
        <button type="submit">${raw(icon("flag", 15))}send flag</button></div>
    </form></dialog>`);
  $("#fl-note", d).focus();
  $("form", d).addEventListener("submit", (e) => {
    e.preventDefault();
    act($('button[type="submit"]', d), async () => {
      await api("/api/flags", { method: "POST", json: { target, target_id: String(targetId), note: $("#fl-note", d).value } });
      d.close();
      toast("Thanks! It's being checked.");
      await onDone();
    });
  });
}

// ---------- the course page: Changes ----------

export async function changesTab(box, c, refresh) {
  const data = await api(`/api/courses/${c.id}/changes?all=1`);
  const open = data.changes.filter((x) => ["working", "pending", "failed"].includes(x.status));
  box.innerHTML = html`
    ${raw(data.review_on ? html`<div class="note small">${data.can_publish ? "Review is on: changes other authors make to this course wait here for you."
    : "Review is on: your changes to this course wait for its owner or an admin."}</div>` : "")}
    <h2>Waiting for review ${raw(open.length ? `<span class="pill accent">${open.length}</span>` : "")}</h2>
    ${raw(open.length ? html`<ul class="changes">${open.map((x) => raw(html`<li>
      <div><b>${x.where}</b> <span class="small muted">${x.kind === "ai" ? "AI" : "by hand"}${x.by ? ` · ${x.by}` : ""} · ${ago(x.created_at)}</span>
        <div class="small">${x.wish}</div></div>
      <span class="row">${raw(x.status === "working" ? `<span class="pill"><span class="spinner" style="width:.8em;height:.8em"></span> writing</span>`
    : x.status === "failed" ? `<span class="pill bad">failed</span>` : x.stale ? `<span class="pill warn">changed since</span>` : "")}
        <button class="small ${x.status === "pending" ? "" : "ghost"}" data-review="${x.id}">${raw(icon("git-compare", 14))}review</button></span></li>`))}</ul>`
    : `<p class="muted small">Nothing waiting. Drafts from the AI (and, with review on, other authors' edits) appear here.</p>`)}
    ${raw(c.status === "ready" ? html`<div class="panel" style="margin-top:1.2rem"><h2 style="margin-top:0">Change the plan</h2>
      <p class="small muted">Rename, move, add or remove sessions. The AI drafts a new plan for you to review; new sessions are written once you accept,
        and sessions people have started stay with them under Earlier sessions.</p>
      <textarea id="rp-wish" placeholder="e.g. Add a session on tides after the Moon one; merge the two review sessions; drop the last project"></textarea>
      <div class="row" style="margin-top:.5rem"><button class="ghost" id="rp-go">${raw(icon("sparkles", 15))}draft a new plan</button>
        <button class="link small" id="rp-hist">${raw(icon("history", 14))}plan history</button></div></div>` : "")}
    <h2 style="margin-top:1.6rem">Recent changes</h2>
    ${raw(data.history.length ? html`<ul class="changes small">${data.history.slice(0, 40).map((x) => raw(html`<li><div><b>${x.where}</b>
      <span class="muted">${SOURCE[x.source] || x.source}${x.who ? ` by ${x.who}` : ""} · ${ago(x.at)}</span><div>${x.why}</div></div>
      <button class="link small" data-hist="${x.target}|${x.target_id}|${x.where}">${raw(icon("history", 14))}history</button></li>`))}</ul>`
    : `<p class="muted small">No changes since the course was written.</p>`)}`;
  $$("[data-review]", box).forEach((b) => b.addEventListener("click", () => openReview(Number(b.dataset.review), refresh)));
  $$("[data-hist]", box).forEach((b) => b.addEventListener("click", () => {
    const [t, id, where] = b.dataset.hist.split("|");
    openHistory(t, id, where.toLowerCase(), refresh);
  }));
  $("#rp-go", box)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/replan`, { method: "POST", json: { wish: $("#rp-wish", box).value } });
    toast("Drafting a new plan. It'll appear above to review.");
    await refresh();
  }));
  $("#rp-hist", box)?.addEventListener("click", () => openHistory("plan", c.id, "the plan", refresh));
  return open.some((x) => x.status === "working");
}

// ---------- the course page: Flags ----------

const VERDICT = { wrong: ["bad", "likely wrong"], right: ["good", "looks right"], unsure: ["", "not sure"] };
const FIX_ICON = { chunk: "sparkles", item: "sparkles", feedback: "refresh-cw", reading: "trash-2" };
const FIX = { chunk: "Fix with the AI", item: "Fix with the AI", feedback: "Mark it again", reading: "Take it off the list" };

export async function flagsTab(box, c, refresh, showClosed = false) {
  const { flags } = await api(`/api/courses/${c.id}/flags${showClosed ? "?all=1" : ""}`);
  box.innerHTML = html`<div class="spread"><h2 style="margin:0">Flags from learners</h2>
      <label class="row small" style="gap:6px"><input type="checkbox" id="fl-closed" ${raw(showClosed ? "checked" : "")}> show closed ones</label></div>
    <p class="small muted">Each flag gets a quick second look from the AI. The ones it thinks are really wrong come first.</p>
    ${raw(flags.length ? html`<ul class="flags">${flags.map((f) => {
    const [cls, label] = VERDICT[f.verdict] || ["", ""];
    const link = f.session_id ? html`<a href="#/session/${f.session_id}">${f.where}</a>` : f.where;
    return raw(html`<li class="flag">
      <div class="spread"><b>${raw(link)}</b><span class="row">${raw(f.status === "checking" ? `<span class="pill"><span class="spinner" style="width:.8em;height:.8em"></span> checking</span>`
      : label ? html`<span class="pill ${cls}">${label}</span>` : "")}${raw(["fixed", "dismissed", "fixing"].includes(f.status) ? html`<span class="pill">${f.status}</span>` : "")}</span></div>
      <div class="small muted">${f.by} · ${ago(f.created_at)}</div>
      ${raw(f.note ? html`<blockquote class="picked small">${f.note}</blockquote>` : "")}
      ${raw(f.reason ? html`<div class="small"><b>Second look:</b> ${f.reason}</div>` : "")}
      ${raw(f.suggestion ? html`<div class="small"><b>Suggested fix:</b> ${f.suggestion}</div>` : "")}
      ${raw(f.reply ? html`<div class="small faint">Reply: ${f.reply}</div>` : "")}
      ${raw(f.status === "open" ? html`<div class="row" style="margin-top:6px">
        <button class="small" data-fix="${f.id}">${raw(icon(FIX_ICON[f.target], 14))}${FIX[f.target]}</button>
        <button class="ghost small" data-done="${f.id}">${raw(icon("check", 14))}I fixed it</button>
        <button class="ghost small" data-dismiss="${f.id}">${raw(icon("x", 14))}It's fine</button></div>` : "")}
      ${raw(f.status === "fixing" && f.change_id ? html`<div class="row" style="margin-top:6px"><button class="small" data-review="${f.change_id}">${raw(icon("git-compare", 14))}review the fix</button></div>` : "")}
    </li>`);
  })}</ul>` : `<p class="muted small">No open flags. When a learner flags a part, a question, feedback or a reading item, it appears here.</p>`)}`;
  const again = () => flagsTab(box, c, refresh, showClosed);
  $("#fl-closed", box).addEventListener("change", (e) => flagsTab(box, c, refresh, e.target.checked));
  $$("[data-fix]", box).forEach((b) => b.addEventListener("click", () => act(b, async () => {
    const r = await api(`/api/flags/${b.dataset.fix}/fix`, { method: "POST", json: {} });
    toast(r.change ? "The AI is drafting a fix. Review it here or under Changes." : r.remarked ? "Marking it again." : "Taken off the reading list.");
    await refresh(); await again();
  })));
  $$("[data-done]", box).forEach((b) => b.addEventListener("click", () => act(b, async () => {
    const reply = prompt("A short note for the person who flagged it (optional):", "Fixed. Thanks!");
    if (reply === null) return;
    await api(`/api/flags/${b.dataset.done}/fixed`, { method: "POST", json: { reply } });
    await refresh(); await again();
  })));
  $$("[data-dismiss]", box).forEach((b) => b.addEventListener("click", () => act(b, async () => {
    const reply = prompt("Why it's fine, for the person who flagged it (optional):", "");
    if (reply === null) return;
    await api(`/api/flags/${b.dataset.dismiss}/dismiss`, { method: "POST", json: { reply } });
    await refresh(); await again();
  })));
  $$("[data-review]", box).forEach((b) => b.addEventListener("click", () => openReview(Number(b.dataset.review), async () => { await refresh(); await again(); })));
  return flags.some((f) => f.status === "checking");
}
