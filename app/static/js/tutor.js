// The tutor: a round chat bubble in the corner of a course or session page. It opens a small chat window above it.
// Questions about one question, or about a passage the learner selected, open the same window.
import { act, api, el, esc, html, raw } from "./util.js";
import { icon } from "./icons.js";
import { md } from "./md.js";

let state = null;   // { courseId, home: {scope, title}, scope, title, fab, panel }

/** Put the bubble on this page. `scope` is "course" or a session id; `title` is what it's about. */
export function mountTutor(courseId, scope, title) {
  if (state && state.courseId === courseId && state.home.scope === scope && state.fab.isConnected) return;   // redraws keep an open chat
  removeTutor();
  const fab = el(html`<button class="tutor-fab" type="button" aria-expanded="false" aria-label="Ask the tutor" title="Ask the tutor">${raw(icon("message-circle", 24))}<span class="dot" hidden></span></button>`);
  document.body.append(fab);
  state = { courseId, home: { scope, title }, scope, title, fab, panel: null, timer: null };
  fab.addEventListener("click", () => (state.panel ? close() : open()));
}

export function removeTutor() {
  if (!state) return;
  clearInterval(state.timer);
  state.fab.remove();
  state.panel?.remove();
  state = null;
}

/** Open the chat about something specific (a question, a selected passage), with an optional draft question. */
/** `quote` is a passage the learner selected, or with `section` set, the title of the section they asked about. */
export function openChat(courseId, scope, title, quote = "", section = false) {
  if (!state || state.courseId !== courseId) mountTutor(courseId, scope, title);
  state.scope = scope;
  state.title = title;
  open(quote, section);
}

function close() {
  clearInterval(state.timer);
  // still waiting for an answer: keep an ear out and light the bubble's dot when it comes
  if (state.panel?.querySelector(".typing")) {
    const st = state;
    const url = `/api/chat?course=${encodeURIComponent(st.courseId)}&scope=${encodeURIComponent(st.scope)}`;
    st.timer = setInterval(async () => {
      if (state !== st || st.panel) return clearInterval(st.timer);
      const r = await api(url).catch(() => null);
      if (r && !r.pending) { clearInterval(st.timer); st.fab.querySelector(".dot").hidden = false; }
    }, 3000);
  }
  state.panel?.remove();
  state.panel = null;
  state.fab.setAttribute("aria-expanded", "false");
  state.fab.focus();
}

function open(quote = "", section = false) {
  state.panel?.remove();
  clearInterval(state.timer);
  const atHome = state.scope === state.home.scope;
  const p = el(html`<section class="tutor-panel" role="dialog" aria-label="Tutor">
    <header><div><b>Tutor</b><div class="small faint">about ${state.title}${raw(atHome ? "" : ` · <button class="link small" data-act="home">back to ${esc(state.home.title)}</button>`)}</div></div>
      <button class="ghost small" data-act="close" aria-label="Close the tutor">${raw(icon("x", 16))}</button></header>
    <div class="tutor-msgs" aria-live="polite"></div>
    ${raw(quote ? html`<div class="tutor-quote"><blockquote class="picked">${section ? `Section: ${quote}` : quote}</blockquote>
      <button type="button" class="link small" data-act="unquote" aria-label="Don't include this passage">${raw(icon("x", 14))}</button></div>` : "")}
    <form class="tutor-input"><textarea rows="2" placeholder="${quote ? "What would you like to know about it?" : "Ask anything… (Enter sends)"}"></textarea>
      <button type="submit" aria-label="Send">${raw(icon("arrow-up", 18))}</button></form>
  </section>`);
  document.body.append(p);
  state.panel = p;
  state.fab.setAttribute("aria-expanded", "true");
  state.fab.querySelector(".dot").hidden = true;
  const list = p.querySelector(".tutor-msgs");
  const ta = p.querySelector("textarea");
  const { courseId, scope } = state;
  const url = `/api/chat?course=${encodeURIComponent(courseId)}&scope=${encodeURIComponent(scope)}`;

  const load = async () => {
    const r = await api(url);
    if (!p.isConnected) return;
    list.innerHTML = (r.messages.length ? "" : `<p class="small muted">Ask for another explanation, an example, or why an answer is right. The tutor reads this course's material.</p>`)
      + r.messages.map((m) => html`<div class="msg ${m.role}">${raw(md(m.text))}</div>`).join("")
      + (r.pending ? `<div class="msg tutor typing"><span></span><span></span><span></span></div>` : "");
    list.scrollTop = list.scrollHeight;
    clearInterval(state.timer);
    if (r.pending) {
      state.timer = setInterval(async () => {
        if (!p.isConnected) return clearInterval(state.timer);
        const again = await api(url);
        if (!again.pending) { clearInterval(state.timer); load(); }
      }, 2500);
    }
  };
  p.querySelector('[data-act="close"]').addEventListener("click", close);
  p.querySelector('[data-act="home"]')?.addEventListener("click", () => { state.scope = state.home.scope; state.title = state.home.title; open(); });
  p.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  p.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!ta.value.trim()) return;
    act(p.querySelector('button[type="submit"]'), async () => {
      const q = !p.querySelector(".tutor-quote") ? "" : section ? `About the section “${quote}”: `
        : `About this passage:\n> ${quote.replace(/\n+/g, "\n> ")}\n\n`;
      await api("/api/chat", { method: "POST", json: { course: courseId, scope, text: q + ta.value } });
      ta.value = "";
      p.querySelector(".tutor-quote")?.remove();
      await load();
    });
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); p.querySelector("form").requestSubmit(); }
  });
  p.querySelector('[data-act="unquote"]')?.addEventListener("click", (e) => { e.currentTarget.parentElement.remove(); ta.focus(); });
  load();
  ta.focus();
}
