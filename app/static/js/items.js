// Questions, exercises and projects: answering them, feedback, showing answers, and editing. The tutor lives in tutor.js.
import { $, act, api, celebrate, el, esc, html, raw, toast } from "./util.js";
import { icon } from "./icons.js";
import { openChat } from "./tutor.js";
import { md } from "./md.js";
import { dialog, openFlag, openHistory, openReview } from "./review.js";

const SECTION = { check: "Quick check", practice: "Practice", exercise: "Written exercise", project: "Project" };

let uid = 0;

export function renderItem(item, ctx) {
  const box = item.qtype === "long" ? longItem(item, ctx) : quickItem(item, ctx);
  box.dataset.item = item.id;
  const draft = (ctx.changes || []).find((x) => x.target === "item" && x.target_id === item.id);
  if (draft) {
    box.prepend(el(draft.status === "working"
      ? `<div class="revising-note small"><span class="spinner"></span> The AI is drafting a new version of this question.</div>`
      : html`<div class="draft-bar small"><span>${raw(icon("git-compare", 14))} ${draft.status === "failed" ? "A rewrite of this question didn't work."
        : draft.kind === "ai" ? "A new version from the AI is ready to review." : `${draft.by || "Someone"} suggested an edit.`}</span>
        <button class="small" data-review="${draft.id}">review</button></div>`));
    box.querySelector("[data-review]")?.addEventListener("click", () => openReview(draft.id, ctx.reload));
  }
  return box;
}

// a question whose answer key changed after this person answered keeps their result, with a note
const changedNote = (item) => (item.changed_since
  ? html`<div class="note small changed">${raw(icon("history", 13))} This question was changed after you answered${item.changed_at ? ` (${new Date(item.changed_at).toLocaleDateString()})` : ""}.
    Your earlier result stays; try it again if you like.</div>` : "");

const editorButtons = (ctx) => (ctx.editing ? `<button class="ghost small" data-act="edit">Edit</button>
  <button class="ghost small" data-act="ai">${icon("sparkles", 14)}Rewrite with the AI</button>
  <button class="ghost small" data-act="history">${icon("history", 14)}History</button>
  <button class="danger small" data-act="delete">Take out</button>` : "");

function replace(box, item, ctx) {
  const fresh = renderItem(item, ctx);
  box.replaceWith(fresh);
  return fresh;
}

function head(item, ctx) {
  const where = ctx.warmup ? `Warm-up · from “${item.from_session}”` : SECTION[item.section] || "";
  return html`<div class="qhead"><span>${where}</span><span>${item.topic || ""}</span></div>`;
}

function quickItem(item, ctx) {
  const last = item.last;
  const right = last && last.status === "marked" && last.score >= 0.999;
  const wrong = last && last.status === "marked" && last.score < 0.999;
  const name = `q${++uid}`;
  let input = "";
  if (item.qtype === "mcq") {
    input = html`<div class="options">${item.options.map((o) => raw(html`<label class="opt"><input type="radio" name="${name}" value="${o}"
      ${raw(last && last.answer === o ? "checked" : "")}><span>${raw(md(o, { inline: true }))}</span></label>`))}</div>`;
  } else if (item.qtype === "numeric") {
    input = html`<input type="text" inputmode="decimal" name="${name}" placeholder="Your answer (a number)" value="${last ? last.answer : ""}">`;
  } else {
    input = html`<textarea name="${name}" rows="3" placeholder="A sentence or two" style="min-height:4.5rem">${last ? last.answer : ""}</textarea>`;
  }
  let result = "";
  if (last && last.status === "queued") result = `<p class="muted row"><span class="spinner"></span> Looking at your answer…</p>`;
  else if (last && last.status === "failed") result = html`<div class="note bad">Couldn't check that: ${last.feedback?.error || "unknown error"}. Try again.</div>`;
  else if (right) result = html`<div class="note good"><b>✓ Right.</b> ${raw(md(item.explanation || "", { inline: true }))}</div>`;
  else if (wrong) result = html`<div class="note warn"><b>Not quite.</b> ${last.feedback?.comment || "Have another go, or show the answer."}
    ${raw(item.qtype === "short" ? `<button class="link small" data-act="flagfb">${icon("flag", 12)}Unfair? Flag this marking</button>` : "")}</div>`;
  if (item.revealed && !right) {
    result += html`<div class="note" style="margin-top:.5rem"><b>Answer:</b> ${raw(md(item.answer || "", { inline: true }))}
      ${item.explanation ? raw(`<div class="small muted" style="margin-top:.3rem">${md(item.explanation, { inline: true })}</div>`) : ""}</div>`;
  }
  const box = el(html`<div class="q ${right ? "right" : wrong ? "wrong" : ""}">
    ${raw(head(item, ctx))}
    <div class="prose">${raw(md(item.prompt))}</div>
    ${raw(input)}
    <div class="actions">
      <button class="small" data-act="check">${last ? "Check again" : "Check"}</button>
      ${raw(!right && !item.revealed ? `<button class="ghost small" data-act="show">Show answer</button>` : "")}
      <button class="link small" data-act="ask">${raw(icon("message-circle-question", 14))}Ask about this</button>
      ${raw(ctx.warmup ? "" : `<button class="link small" data-act="flag" title="Something wrong with this question or its answer?">${icon("flag", 13)}Flag</button>`)}
      ${raw(editorButtons(ctx))}
    </div>
    <div class="result">${raw(changedNote(item))}${raw(result)}</div>
  </div>`);
  wire(box, item, ctx, () => {
    if (item.qtype === "mcq") return box.querySelector(`input[name="${name}"]:checked`)?.value || "";
    return box.querySelector(`[name="${name}"]`).value;
  });
  if (last && last.status === "queued") follow(box, item, ctx);
  return box;
}

function feedbackBlock(item) {
  const last = item.last;
  if (!last) return "";
  if (last.status === "queued") return `<p class="muted row feedback"><span class="spinner"></span> Gemini is reading your work…</p>`;
  if (last.status === "failed") return html`<div class="note bad feedback">Couldn't get feedback: ${last.feedback?.error || "unknown error"}. Send it again.</div>`;
  const fb = last.feedback || {};
  const lvl = (fb.level || "").split(" ")[0];
  return html`<div class="note feedback">
    <div class="spread"><span class="level ${lvl}">${fb.level || ""}</span><span class="small muted">${last.created_at ? new Date(last.created_at).toLocaleString() : ""}</span></div>
    <div class="prose" style="margin-top:.5rem">${raw(md(fb.overall || ""))}</div>
    <table class="lines"><tbody>${(fb.lines || []).map((l) => raw(html`<tr><td><b>${l.criterion}</b></td>
      <td>${fmtPts(l.awarded)} / ${fmtPts(l.points)}</td><td>${raw(md(l.comment, { inline: true }))}</td></tr>`))}</tbody></table>
    ${raw((fb.revisit || []).length ? html`<p class="small"><b>Worth revisiting:</b> ${fb.revisit.join(" · ")}</p>` : "")}
    <button class="link small" data-act="flagfb">${raw(icon("flag", 12))}Unfair? Flag this feedback</button>
  </div>`;
}

const fmtPts = (n) => (Number.isInteger(n) ? n : Number(n).toFixed(1));

function longItem(item, ctx) {
  const last = item.last;
  const name = `l${++uid}`;
  const files = last && last.files.length
    ? html`<p class="small muted">Sent with your last answer: ${last.files.map((f) => raw(html`<a href="/api/uploads/${last.id}/${f.split("/").pop()}">${f.split("/").pop()}</a> `))}</p>`
    : "";
  const box = el(html`<div class="q long">
    ${raw(head(item, ctx))}
    ${raw(item.title ? html`<h3>${item.title}</h3>` : "")}
    <div class="prose">${raw(md(item.prompt))}</div>
    ${raw(item.rubric.length ? html`<details class="rubric"><summary>What good looks like</summary><ul>${item.rubric.map((r) =>
      raw(html`<li><b>${r.criterion}</b> (${r.points}): ${r.description}</li>`))}</ul></details>` : "")}
    <textarea name="${name}" rows="7" placeholder="Write your answer. Markdown and $maths$ work.">${last ? last.answer : ""}</textarea>
    <div class="row small" style="margin-top:.4rem">
      <label class="muted">Add a photo or PDF of your working: <input type="file" multiple accept=".png,.jpg,.jpeg,.webp,.gif,.heic,.pdf,.txt,.md"></label>
    </div>
    ${raw(files)}
    <div class="actions">
      <button class="small" data-act="check">${last ? "Send again for feedback" : "Get feedback"}</button>
      <button class="ghost small" data-act="preview">Preview</button>
      ${raw(!item.revealed ? `<button class="ghost small" data-act="show">Show model answer</button>` : "")}
      <button class="link small" data-act="ask">${raw(icon("message-circle-question", 14))}Ask about this</button>
      ${raw(ctx.warmup ? "" : `<button class="link small" data-act="flag" title="Something wrong with this exercise?">${icon("flag", 13)}Flag</button>`)}
      ${raw(editorButtons(ctx))}
    </div>
    ${raw(changedNote(item))}
    <div class="preview prose" hidden></div>
    ${raw(feedbackBlock(item))}
    ${raw(item.revealed ? html`<details class="example" open><summary>Model answer</summary><div class="prose">${raw(md(item.answer || ""))}</div></details>` : "")}
  </div>`);
  const ta = box.querySelector("textarea");
  box.querySelector('[data-act="preview"]').addEventListener("click", () => {
    const p = box.querySelector(".preview");
    p.hidden = !p.hidden;
    p.innerHTML = md(ta.value || "_Nothing yet._");
  });
  wire(box, item, ctx, () => ta.value, () => box.querySelector('input[type="file"]').files);
  if (last && last.status === "queued") follow(box, item, ctx);
  return box;
}

function wire(box, item, ctx, getAnswer, getFiles = () => []) {
  box.querySelector('[data-act="check"]').addEventListener("click", (e) => act(e.currentTarget, async () => {
    const form = new FormData();
    form.append("answer", getAnswer());
    form.append("context", ctx.warmup ? "warmup" : "session");
    for (const f of getFiles()) form.append("files", f);
    const updated = await api(`/api/items/${item.id}/attempts`, { method: "POST", form });
    celebrate(updated.achievements);
    if (ctx.warmup) updated.from_session = item.from_session;
    replace(box, updated, ctx);
    ctx.onChange?.();
  }));
  box.querySelector('[data-act="show"]')?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    const updated = await api(`/api/items/${item.id}/reveal`, { method: "POST" });
    if (ctx.warmup) updated.from_session = item.from_session;
    replace(box, updated, ctx);
  }));
  box.querySelector('[data-act="ask"]').addEventListener("click", () =>
    openChat(ctx.courseId, item.id, item.title || "this question"));
  box.querySelector('[data-act="edit"]')?.addEventListener("click", () => editItem(box, item, ctx));
  box.querySelector('[data-act="delete"]')?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    if (!confirm("Take this question out of the session? Answers people gave are kept.")) return;
    await api(`/api/items/${item.id}`, { method: "DELETE" });
    box.remove();
  }));
  box.querySelector('[data-act="flag"]')?.addEventListener("click", () => openFlag("item", item.id));
  box.querySelector('[data-act="flagfb"]')?.addEventListener("click", () => openFlag("feedback", item.last.id));
  box.querySelector('[data-act="history"]')?.addEventListener("click", () => openHistory("item", item.id, "this question", ctx.reload));
  box.querySelector('[data-act="ai"]')?.addEventListener("click", () => aiItem(item, ctx));
}

function follow(box, item, ctx) {
  const t = setInterval(async () => {
    if (!box.isConnected) return clearInterval(t);
    try {
      const updated = await api(`/api/items/${item.id}`);
      if (updated.last && updated.last.status !== "queued") {
        clearInterval(t);
        if (ctx.warmup) updated.from_session = item.from_session;
        replace(box, updated, ctx);
        ctx.onChange?.();
      }
    } catch { /* retry */ }
  }, 2500);
}

function editItem(box, item, ctx) {
  const form = el(html`<div class="edit-box">
    <label class="field">Question</label><textarea data-f="prompt">${item.prompt}</textarea>
    ${raw(item.qtype === "mcq" ? html`<label class="field" style="margin-top:.6rem">Options, one per line</label>
      <textarea data-f="options" style="min-height:6rem">${item.options.join("\n")}</textarea>` : "")}
    <label class="field" style="margin-top:.6rem">${item.qtype === "long" ? "Model answer" : "Answer"}</label>
    <textarea data-f="answer" style="min-height:${item.qtype === "long" ? "10rem" : "3rem"}" placeholder="Hidden answers are loaded when you save"></textarea>
    <label class="field" style="margin-top:.6rem">Explanation</label><textarea data-f="explanation" style="min-height:4rem"></textarea>
    <div class="row" style="margin-top:.6rem"><button class="small" data-act="save">Save</button><button class="ghost small" data-act="cancel">Cancel</button></div>
  </div>`);
  const f = (k) => form.querySelector(`[data-f="${k}"]`);
  // editors load the answer without it counting as "revealed" for their own progress
  api(`/api/items/${item.id}/full`).then((full) => {
    f("answer").value = full.answer || "";
    f("explanation").value = full.explanation || "";
  });
  box.replaceWith(form);
  form.querySelector('[data-act="cancel"]').addEventListener("click", async () => form.replaceWith(renderItem(await api(`/api/items/${item.id}`), ctx)));
  form.querySelector('[data-act="save"]').addEventListener("click", (e) => act(e.currentTarget, async () => {
    const updated = await api(`/api/items/${item.id}`, { method: "PUT", json: {
      prompt: f("prompt").value, options: f("options") ? f("options").value.split("\n") : [],
      answer: f("answer").value, explanation: f("explanation").value } });
    form.replaceWith(renderItem(updated, ctx));
    toast(updated.applied ? "Saved." : "Sent for review: the course's owner or an admin accepts it.");
    if (!updated.applied) ctx.reload?.();
  }));
}

function aiItem(item, ctx) {
  const d = dialog(html`<dialog class="modal" aria-label="Rewrite a question">
    <form class="modal-body">
      <h2 style="margin:0">Rewrite <span class="tone2">this question with the AI.</span></h2>
      <p class="small muted" style="margin:4px 0 0">It stays the same kind of question. The new version comes back as a draft to review;
        people who already answered keep their result, with a note that it changed.</p>
      <div><label class="field" for="ai-wish">What should change?</label>
        <textarea id="ai-wish" required placeholder="e.g. harder, a real-world setting, fix the answer key, clearer wording"></textarea></div>
      ${raw(ctx.canPublish ? `<label class="row small" style="gap:6px"><input type="checkbox" id="ai-now"> Publish it straight away, without reviewing</label>` : "")}
      <div class="row modal-actions"><span style="flex:1"></span><button type="button" class="ghost" data-close>cancel</button>
        <button type="submit">${raw(icon("sparkles", 15))}rewrite</button></div>
    </form></dialog>`);
  d.querySelector("#ai-wish").focus();
  d.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    act(d.querySelector('button[type="submit"]'), async () => {
      await api(`/api/items/${item.id}/revise`, { method: "POST", json: { wish: d.querySelector("#ai-wish").value,
        publish_now: !!d.querySelector("#ai-now")?.checked } });
      d.close();
      toast("The AI is drafting it. It'll be here to review in a minute.");
      await ctx.reload?.();
    });
  });
}

export { $ };
export { openChat };
