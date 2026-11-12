import { $, $$, act, api, can, html, raw, team, toast, money, hours, KIND_LABEL } from "../util.js";
import { readingSwitch, wireReadingSwitch } from "../readingmode.js";
import { icon, KIND_ICON } from "../icons.js";
import { md } from "../md.js";
import { mountTutor } from "../tutor.js";

const WAITING = {
  questions: ["Writing a few questions for you…", "This takes a few seconds."],
  planning: ["Planning your course…", "Gemini's top model is laying out the sessions. Usually under a minute."],
};

export default async function course(view, scope, id, tab = "sessions") {
  let c = await api(`/api/courses/${id}`);
  const draw = () => {
    if (!c.can_edit && !["building", "ready"].includes(c.status)) {
      view.innerHTML = html`<p class="crumbs"><a href="#/">Courses</a></p><h1>${c.title}</h1>
        <div class="panel"><p class="muted" style="margin:0">This course is still being prepared by ${c.author || "its author"}. Check back soon.</p></div>`;
      return undefined;
    }
    if (c.status === "questions" || c.status === "planning") return drawWaiting(view, c);
    if (c.status === "answering") return drawQuestions(view, c);
    if (c.status === "review") return drawPlan(view, c);
    return drawClassroom(view, c, tab);
  };
  draw();
  scope.every(4000, async () => {
    const fresh = await api(`/api/courses/${id}`);
    const changedStatus = fresh.status !== c.status;
    const busy = fresh.jobs.length > 0 || fresh.reading_checking > 0;
    const wasBusy = c.jobs.length > 0 || c.reading_checking > 0;
    c = fresh;
    if (changedStatus) draw();
    else if ((busy || wasBusy) && (c.status === "building" || c.status === "ready")) refreshClassroom(view, c);
    else if (c.status === "questions" || c.status === "planning") drawWaiting(view, c);
    return true;
  });
}

function errorNote(c) {
  if (!c.error && !c.failed_jobs) return "";
  return html`<div class="note bad spread" style="margin-bottom:1rem"><span>${c.error || "Some steps failed."}</span>
    <button class="small ghost" data-act="retry">${raw(icon("refresh-cw", 14))}Try again</button></div>`;
}

function wireRetry(view, c) {
  $('[data-act="retry"]', view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/retry`, { method: "POST" });
    toast("Trying again.");
  }));
}

function drawWaiting(view, c) {
  const [title, sub] = WAITING[c.status];
  view.innerHTML = html`<p class="crumbs"><a href="#/">Courses</a> › ${c.depth_label}</p>
    <h1>${c.subject}</h1>
    ${raw(errorNote(c))}
    <div class="panel"><p class="row" style="margin:0"><span class="spinner"></span> <b>${title}</b></p>
      <p class="muted small" style="margin:.4rem 0 0">${sub}</p>
      ${raw(c.status === "questions" ? `<p style="margin:.8rem 0 0"><button class="ghost small" data-act="skip">Skip the questions and plan now</button></p>` : "")}
    </div>`;
  wireRetry(view, c);
  $('[data-act="skip"]', view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/skip-questions`, { method: "POST" });
    c.status = "planning";
    drawWaiting(view, c);
  }));
}

function drawQuestions(view, c) {
  view.innerHTML = html`<p class="crumbs"><a href="#/">Courses</a> › ${c.depth_label}</p>
    <h1>${c.subject}</h1>
    <p class="muted">A few questions so the course fits you. Answer as much or as little as you like.</p>
    ${raw(errorNote(c))}
    <form class="panel stack" id="qa">
      ${c.questions.map((q) => raw(html`<div><label class="field">${q.text}</label>${raw(q.kind === "choice" && q.options.length
        ? html`<div class="row">${q.options.map((o) => raw(html`<label class="pill" style="cursor:pointer;padding:.35em .8em">
            <input type="radio" name="${q.id}" value="${o}" style="accent-color:var(--accent)"> ${o}</label>`))}
            <input type="text" name="${q.id}__other" placeholder="Or in your own words" style="max-width:20rem"></div>`
        : html`<input type="text" name="${q.id}" maxlength="2000">`)}</div>`))}
      <div class="row"><button type="submit" id="send">Plan my course</button>
        <button type="button" class="ghost" data-act="skip">Skip</button></div>
    </form>`;
  wireRetry(view, c);
  const form = $("#qa", view);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#send", view), async () => {
      const answers = {};
      for (const q of c.questions) {
        const picked = form.querySelector(`input[name="${CSS.escape(q.id)}"]:checked`)?.value;
        const typed = form.querySelector(`input[name="${CSS.escape(q.id)}"][type=text], input[name="${CSS.escape(q.id + "__other")}"]`)?.value?.trim();
        const v = typed || picked;
        if (v) answers[q.id] = v;
      }
      await api(`/api/courses/${c.id}/answers`, { method: "POST", json: { answers } });
      c.status = "planning";
      drawWaiting(view, c);
    });
  });
  $('[data-act="skip"]', view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/skip-questions`, { method: "POST" });
    c.status = "planning";
    drawWaiting(view, c);
  }));
}

const BAND_NOTE = {
  teaching: "How well a text course can teach this",
  feedback: "How useful Gemini's feedback on written answers will be",
};

function drawPlan(view, c) {
  const p = c.plan;
  const total = p.sessions.reduce((n, s) => n + (s.minutes || 0), 0);
  view.innerHTML = html`<p class="crumbs"><a href="#/">Courses</a> › Plan</p>
    <div class="spread"><h1 style="margin:0">${p.title}</h1><span class="pill accent">${c.depth_label}</span></div>
    <p class="goal" style="margin-top:.6rem">${p.summary}</p>
    ${raw(errorNote(c))}
    ${raw(p.readiness.safety_note ? html`<div class="note warn" style="margin-bottom:1rem">${p.readiness.safety_note}</div>` : "")}
    <div class="panel">
      <h2>How well this will work</h2>
      <div class="bands">
        ${["teaching", "feedback"].map((k) => raw(html`<div class="band"><div class="small muted">${BAND_NOTE[k]}</div><div class="v">${p.readiness[k]}</div></div>`))}
      </div>
      ${raw(p.readiness.weak_spots.length ? html`<p style="margin:.9rem 0 .3rem"><b>Weak spots</b></p><ul>${p.readiness.weak_spots.map((w) => raw(html`<li>${w}</li>`))}</ul>` : "")}
      ${raw(p.prerequisites.length ? html`<p style="margin:.9rem 0 .3rem"><b>Good to know first</b></p><ul>${p.prerequisites.map((w) => raw(html`<li>${w}</li>`))}</ul>` : "")}
    </div>
    <div class="panel">
      <div class="spread"><h2 style="margin:0">${p.sessions.length} sessions</h2><span class="muted small">${total ? `about ${hours(total)} in all` : ""}</span></div>
      <ul class="slots" style="margin-top:.6rem">${p.sessions.map((s) => raw(html`<li>
        <span class="num ${s.kind !== "lesson" ? "special" : ""}">${s.slot}</span>
        <div><b>${s.title}</b><div class="small muted">${s.topics.join(" · ")}</div>
          ${raw(s.objectives.length ? html`<div class="small faint">${s.objectives.join(" ")}</div>` : "")}</div>
        <span class="pill ${s.kind !== "lesson" ? "teal" : ""}">${kindLabel(s.kind)}</span></li>`))}</ul>
    </div>
    <div class="panel">
      <div class="row"><button id="approve">${raw(icon("check", 15))}Looks good, write it</button>
        <span class="small muted">Gemini writes every session in the background; you can start as soon as the first one is ready.</span></div>
      <details style="margin-top:1rem"><summary class="muted" style="cursor:pointer">Ask for changes instead</summary>
        <textarea id="changes" style="margin-top:.6rem" placeholder="e.g. More about the history, less maths; add a session on improvisation."></textarea>
        <button class="ghost" id="change" style="margin-top:.5rem">${raw(icon("refresh-cw", 15))}Re-plan with these changes</button></details>
    </div>`;
  wireRetry(view, c);
  $("#approve", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/approve`, { method: "POST" });
    location.hash = `#/course/${c.id}`;
    c = await api(`/api/courses/${c.id}`);
    drawClassroom(view, c, "sessions");
  }));
  $("#change", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/changes`, { method: "POST", json: { text: $("#changes", view).value } });
    c.status = "planning";
    drawWaiting(view, c);
  }));
}

const kindLabel = (k) => ({ lesson: "Lesson", review: "Review", checkpoint: "Put it together", project: "Project", wrapup: "Wrap-up" }[k] || k);

// ---------- the classroom ----------

const TABS = [["sessions", "Sessions"], ["reading", "Further reading"], ["materials", "Materials", true], ["manage", "Course", true]];
const TAB_ICON = { sessions: "list", reading: "book-open", materials: "paperclip", manage: "sliders-horizontal" };
const tabsFor = (c) => TABS.filter(([, , editorsOnly]) => !editorsOnly || c.can_edit);

function header(c) {
  const p = c.progress;
  const ready = c.sessions.filter((s) => s.state === "ready").length;
  const building = c.status === "building";
  return html`<p class="crumbs"><a href="#/">Courses</a> › ${c.depth_label}</p>
    <h1>${c.title}</h1><p class="summary">${c.summary}</p>
    ${raw(team() ? html`<div class="row small faint" style="gap:6px">${raw(c.visibility === "draft" ? `<span class="pill teal">draft</span>` : "")}
      <span>by ${c.author}</span></div>` : "")}
    <div class="stats">
      <div class="stat"><span>${c.reading_mode ? "Sessions read" : "Sessions done"}</span><b>${p.done} / ${p.sessions}</b></div>
      <div class="bar"><span style="width:${p.sessions ? Math.round((p.done / p.sessions) * 100) : 0}%"></span></div>
      ${raw(c.reading_mode ? "" : html`<div class="stat"><span>Questions answered</span><b>${p.answered}</b></div>`)}
      ${raw(p.written_done && !c.reading_mode ? html`<div class="stat"><span>Written pieces sent</span><b>${p.written_done}</b></div>` : "")}
      ${raw(p.due_reviews && !c.reading_mode ? html`<div class="stat"><span>Ready to revisit</span><b>${p.due_reviews}</b></div>` : "")}
      ${raw(building ? html`<div class="stat"><span class="row"><span class="spinner"></span> Writing</span><b>${ready} / ${c.sessions.length} ready</b></div>` : "")}
    </div>
    ${raw(p.next ? html`<a class="button" href="#/session/${p.next}" style="width:100%">${p.done ? "Continue" : "Start"}</a>` : "")}
    <div class="rm-box">${raw(readingSwitch(c.reading_mode))}</div>`;
}

function tabLabel(c, k, l) {
  const n = k === "reading" ? c.reading.filter((r) => !r.session_id && r.kind !== "source").length : k === "materials" ? c.materials.length : 0;
  return html`${raw(icon(TAB_ICON[k], 16))}<span>${l}</span>${raw(n ? `<span class="pill">${n}</span>` : "")}`;
}

function drawClassroom(view, c, tab) {
  view.classList.add("fill");
  view.innerHTML = html`<div class="split">
    <aside class="side"><div id="head">${raw(header(c))}</div>
      <nav class="vtabs" role="tablist" aria-label="Course sections">${tabsFor(c).map(([k, l]) => raw(html`<button role="tab" data-tab="${k}"
        class="${k === tab ? "on" : ""}" aria-selected="${k === tab}">${raw(tabLabel(c, k, l))}</button>`))}</nav></aside>
    <section class="pane" id="pane"><div id="err">${raw(errorNote(c))}</div><div id="tab"></div></section></div>`;
  wireRetry(view, c);
  wireReadingSwitch($("#head", view), c.id, async (on) => {
    c.reading_mode = on;
    $("#head", view).innerHTML = header(c);
    if (view.dataset.tab === "sessions") drawTab(view, c, "sessions");
  });
  $$("[data-tab]", view).forEach((b) => b.addEventListener("click", () => {
    history.replaceState(null, "", `#/course/${c.id}/${b.dataset.tab}`);
    $$("[data-tab]", view).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
    view.dataset.tab = b.dataset.tab;
    $("#pane", view).scrollTop = 0;
    drawTab(view, c, b.dataset.tab);
  }));
  if (!tabsFor(c).some(([k]) => k === tab)) tab = "sessions";
  view.dataset.tab = tab;
  drawTab(view, c, tab);
  mountTutor(c.id, "course", "this course");
}

function refreshClassroom(view, c) {
  const head = $("#head", view);
  if (!head) return drawClassroom(view, c, view.dataset.tab || "sessions");
  head.innerHTML = header(c);
  $$("[data-tab]", view).forEach((b) => { b.innerHTML = tabLabel(c, b.dataset.tab, TABS.find(([k]) => k === b.dataset.tab)[1]); });
  $("#err", view).innerHTML = errorNote(c);
  wireRetry(view, c);
  if (["sessions", "reading"].includes(view.dataset.tab)) drawTab(view, c, view.dataset.tab);
}

function drawTab(view, c, tab) {
  const box = $("#tab", view);
  if (tab === "reading") return readingTab(box, c);
  if (tab === "materials") return materialsTab(box, c);
  if (tab === "manage") return manageTab(box, c);
  sessionsTab(box, c);
}

const STATE = { pending: "Waiting", writing: "Writing…", checking: "Checking…", failed: "Failed", ready: "" };

function sessionsTab(box, c) {
  const next = c.progress.next;
  box.innerHTML = html`<ul class="sessions">${c.sessions.map((s) => {
    const ready = s.state === "ready";
    const pr = s.progress;
    const bits = [kindLabel(s.kind), `${s.minutes} min`];
    if (ready && pr && pr.tried && !c.reading_mode) bits.push(`${pr.tried}/${pr.questions} answered`);
    return raw(html`<li class="${s.id === next ? "next" : ""}">
      <span class="num ${s.done ? "done" : s.kind !== "lesson" ? "special" : ""}">${s.done ? "✓" : s.seq}</span>
      <div>${raw(ready ? html`<a class="t" href="#/session/${s.id}">${s.title}</a>` : html`<span class="t muted">${s.title}</span>`)}
        <div class="sub">${bits.join(" · ")}${raw(s.error ? html` · <span style="color:var(--bad)">${s.error}</span>` : "")}</div></div>
      <span>${raw(ready ? (s.id === next ? `<span class="pill accent">Up next</span>` : "")
        : s.state === "failed" ? `<span class="pill bad">Failed</span>` : html`<span class="pill"><span class="spinner" style="width:.8em;height:.8em"></span> ${STATE[s.state]}</span>`)}</span>
    </li>`);
  })}</ul>`;
}

function readingTab(box, c) {
  const course = c.reading.filter((r) => !r.session_id && r.kind !== "source");
  const perSession = c.reading.filter((r) => r.session_id && r.kind !== "source");
  const sources = c.reading.filter((r) => r.kind === "source");
  const item = (r) => raw(html`<li class="${r.top ? "top" : ""}"><span class="kind">${raw(icon(KIND_ICON[r.kind] || "link", 13))}${KIND_LABEL[r.kind] || "Link"}</span><div>
    <div class="t">${raw(r.url ? html`<a href="${r.url}" target="_blank" rel="noopener noreferrer">${r.title}</a>` : html`${r.title}`)}
      ${raw(r.top ? `<span class="pill accent">If you only pick one</span>` : "")}</div>
    <div class="small muted">${[r.creator, r.year, r.kind, r.level, r.minutes ? hours(r.minutes) : "", r.free ? "free" : "paid"].filter(Boolean).join(" · ")}</div>
    <div class="small">${r.why}</div>
    ${raw(r.session_title ? html`<div class="small faint">For session ${r.session_seq}: ${r.session_title}</div>` : "")}
  </div></li>`);
  box.innerHTML = html`
    ${raw(c.reading_checking ? html`<p class="muted row small"><span class="spinner"></span> Checking ${c.reading_checking} suggestion${c.reading_checking > 1 ? "s" : ""}: every book, video and link is looked up before it's shown.</p>` : "")}
    ${raw(course.length ? html`<h2>For the whole course</h2><ul class="reading">${course.map(item)}</ul>`
      : c.reading_checking ? "" : `<p class="muted">No reading list yet. It's made after the plan is approved.</p>`)}
    ${raw(perSession.length ? html`<h2 style="margin-top:2rem">Session by session</h2><ul class="reading">${perSession.map(item)}</ul>` : "")}
    ${raw(sources.length ? html`<details style="margin-top:1.5rem"><summary><b>Sources Gemini looked at while writing</b>
      <span class="small muted">(${sources.length}, from live research)</span></summary>
      <ul class="materials" style="margin-top:8px">${sources.map((r) => raw(html`<li><a href="${r.url}" target="_blank" rel="noopener noreferrer">${r.title}</a>
        <span class="small faint">${r.session_seq ? `session ${r.session_seq}` : ""}</span></li>`))}</ul></details>` : "")}
    ${raw(c.reading_dropped ? html`<p class="small faint" style="margin-top:1.2rem">${c.reading_dropped} suggestion${c.reading_dropped > 1 ? "s" : ""} left out because the book, video or page couldn't be found.</p>` : "")}`;
}

function materialsTab(box, c) {
  box.innerHTML = html`<div class="panel">
    <h2>Your materials</h2>
    <p class="muted">Notes, a textbook chapter, past work: Gemini reads these when it writes sessions and gives feedback.
      Add them before approving the plan if you want every session to use them.</p>
    ${raw(c.materials.length ? html`<ul class="materials">${c.materials.map((m) => raw(html`<li><a href="/api/materials/${m.id}">${m.name}</a>
      <span class="row small muted">${(m.bytes / 1024).toFixed(0)} KB <button class="link small" data-del="${m.id}">Remove</button></span></li>`))}</ul>`
      : `<p class="small faint">Nothing yet.</p>`)}
    <div class="row"><input type="file" id="mf" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.heic,.txt,.md,.csv,.json,.tex,.py,.html,.xml,.yaml,.yml" style="max-width:24rem">
      <button class="ghost" id="up">${raw(icon("paperclip", 15))}Add files</button></div>
    <details style="margin-top:1rem"><summary class="muted" style="cursor:pointer">Or type a note</summary>
      <input type="text" id="nt" placeholder="Title" style="margin-top:.6rem"><textarea id="nx" style="margin-top:.5rem" placeholder="What you already know, a wish for the course…"></textarea>
      <button class="ghost" id="addnote" style="margin-top:.5rem">${raw(icon("notebook-pen", 15))}Save note</button></details>
  </div>`;
  const reload = async () => {
    Object.assign(c, await api(`/api/courses/${c.id}`));
    materialsTab(box, c);
  };
  $("#up", box).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const files = $("#mf", box).files;
    if (!files.length) throw new Error("Pick some files first.");
    const form = new FormData();
    for (const f of files) form.append("files", f);
    await api(`/api/courses/${c.id}/materials`, { method: "POST", form });
    await reload();
  }));
  $("#addnote", box).addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/notes`, { method: "POST", json: { title: $("#nt", box).value || "Note", text: $("#nx", box).value } });
    await reload();
  }));
  $$("[data-del]", box).forEach((b) => b.addEventListener("click", () => act(b, async () => {
    await api(`/api/materials/${b.dataset.del}`, { method: "DELETE" });
    await reload();
  })));
}

function manageTab(box, c) {
  box.innerHTML = html`<div class="panel stack">
    <div><label class="field" for="ti">Title</label><div class="row"><input type="text" id="ti" value="${c.title}" style="max-width:32rem">
      <button class="ghost" id="rename">${raw(icon("pencil", 15))}Rename</button></div></div>
    ${raw(team() ? html`<div class="note ${c.visibility === "draft" ? "warn" : ""}"><div class="spread">
      <span>${c.visibility === "draft" ? "Draft: only you and admins can see this course." : "Published: everyone can take this course."}</span>
      <button class="${c.visibility === "draft" ? "" : "ghost"} small" id="publish">${c.visibility === "draft" ? "publish" : "back to draft"}</button></div>
      ${raw(c.visibility === "draft" ? "" : `<div class="small faint">Taking it back to a draft hides it; people's progress is kept.</div>`)}</div>` : "")}
    <div class="small muted">Subject: ${c.subject} · Depth: ${c.depth_label}${raw(c.spend !== undefined ? html` · AI spend on this course so far: ${money(c.spend)}` : "")}</div>
    ${raw(c.plan && c.plan.prerequisites.length ? html`<div><b>Good to know first</b><ul>${c.plan.prerequisites.map((x) => raw(html`<li>${x}</li>`))}</ul></div>` : "")}
    <div><label class="field">What lessons can include</label>
      <div class="field-hint">Applies to sessions written from now on (new ones and rewrites).</div>
      <div class="extras" id="extras"></div></div>
    <div class="row"><a class="button ghost" href="/api/courses/${c.id}/export">${raw(icon("download", 15))}Download as Markdown (zip)</a></div>
    <hr><div class="row"><button class="danger" id="del">${raw(icon("trash-2", 15))}Delete this course</button>
      <span class="small muted">Removes its sessions, ${team() ? "everyone's answers" : "your answers"} and materials. Can't be undone.</span></div>
  </div>`;
  api("/api/extras").then((extras) => {
    const holder = $("#extras", box);
    if (!holder) return;
    holder.innerHTML = extras.map((x) => html`<label class="extra"><input type="checkbox" value="${x.key}" ${raw(c.options[x.key] ? "checked" : "")}>
      <div><b>${x.label}</b><span>${x.hint}</span></div></label>`).join("");
    holder.querySelectorAll("input").forEach((cb) => cb.addEventListener("change", async () => {
      const options = Object.fromEntries([...holder.querySelectorAll("input")].map((x) => [x.value, x.checked]));
      try {
        c.options = (await api(`/api/courses/${c.id}/options`, { method: "PUT", json: { options } })).options;
        toast("Saved.");
      } catch (err) { toast(err.message, true); }
    }));
  });
  $("#publish", box)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    const publish = c.visibility === "draft";
    if (publish && !["building", "ready"].includes(c.status) && !confirm("The course isn't fully written yet. Publish anyway?")) return;
    c.visibility = (await api(`/api/courses/${c.id}/visibility`, { method: "POST", json: { published: publish } })).visibility;
    toast(publish ? "Published. Everyone can take it now." : "Back to a draft.");
    drawClassroom(view_of(box), c, "manage");
  }));
  $("#rename", box).addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api(`/api/courses/${c.id}/title`, { method: "PUT", json: { title: $("#ti", box).value } });
    c.title = $("#ti", box).value;
    toast("Renamed.");
  }));
  $("#del", box).addEventListener("click", (e) => act(e.currentTarget, async () => {
    if (!confirm(`Delete “${c.title}” and everything in it?`)) return;
    await api(`/api/courses/${c.id}`, { method: "DELETE" });
    location.hash = "#/";
  }));
}

export { md };

const view_of = (el) => el.closest("#view");
