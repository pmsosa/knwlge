import { api, can, html, raw, ago, team } from "../util.js";
import { icon } from "../icons.js";

const STATUS = {
  questions: "Writing a few questions", answering: "Waiting for your answers", planning: "Planning",
  review: "Plan ready to review", building: "Writing sessions", ready: "",
};

export default async function home(view, scope) {
  const courses = await api("/api/courses");
  const draw = (courses) => {
    const going = courses.find((c) => c.progress.next && c.progress.done < c.progress.sessions);
    view.innerHTML = html`
      <div class="hero"><span class="iso" aria-hidden="true"></span>
        <div><div class="eyebrow">self-paced learning</div><h1>Your courses<br><span class="tone2">learn anything, at your own pace.</span></h1><p>No deadlines, no grades: just progress.</p></div>
        ${raw(can("author") ? `<a class="button" href="#/new">${icon("plus", 15)}New course</a>` : "")}
      </div>
      ${raw(going ? html`<div class="panel continue">
        <div><div class="small muted">Continue where you left off</div><h2>${going.title}</h2>
          <div class="small muted">${going.progress.done} of ${going.progress.sessions} sessions done${raw(going.progress.due_reviews && !going.reading_mode
            ? html` · ${going.progress.due_reviews} to revisit in the next warm-up` : "")}</div></div>
        <a class="button" href="#/session/${going.progress.next}">Continue${raw(icon("chevron-right", 15))}</a></div>` : "")}
      ${raw(courses.length ? html`<div class="grid">${courses.map((c) => raw(card(c)))}</div>` : html`
        <div class="panel empty"><div class="big">What do you want to learn?</div>
          <p class="muted">Name any subject, pick how deep to go, and Gemini writes you a course.</p>
          ${raw(can("author") ? `<a class="button" href="#/new">${icon("plus", 15)}Start your first course</a>` : `<p class="small faint">When an author publishes a course, it shows up here.</p>`)}</div>`)}`;
  };
  draw(courses);
  if (courses.some((c) => c.status !== "ready")) {
    scope.every(5000, async () => {
      const fresh = await api("/api/courses");
      draw(fresh);
      return fresh.some((c) => c.status !== "ready");
    });
  }
}

function card(c) {
  const p = c.progress;
  const share = p.sessions ? p.done / p.sessions : 0;
  const state = STATUS[c.status];
  return html`<a class="panel card" href="#/course/${c.id}">
    <div class="spread"><span class="row" style="gap:6px"><span class="pill accent">${c.depth_label}</span>${raw(c.visibility === "draft" && team()
      ? `<span class="pill teal">draft</span>` : "")}</span>${raw(state && c.can_edit ? html`<span class="pill teal">${state}</span>` : "")}</div>
    <h3>${c.title}</h3>
    <div class="sum">${c.summary || c.subject}</div>
    ${raw(team() && c.author ? html`<div class="small faint">by ${c.author}</div>` : "")}
    ${raw(c.error ? html`<div class="small" style="color:var(--bad)">Needs attention: ${c.error}</div>` : "")}
    ${raw(p.sessions ? html`<div class="bar"><span style="width:${Math.round(share * 100)}%"></span></div>` : "")}
    <div class="foot"><span>${p.sessions ? `${p.done} / ${p.sessions} sessions` : ""}</span>
      <span>${raw(c.reading_mode ? `${icon("book-open", 12)} Reading mode` : p.due_reviews ? `${icon("refresh-cw", 12)} ${p.due_reviews} to revisit`
        : ago(c.last_opened_at || c.created_at))}</span></div>
  </a>`;
}
