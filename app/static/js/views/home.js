import { api, can, html, raw, ago, team, toast } from "../util.js";
import { icon } from "../icons.js";
import { feedLine } from "../feed.js";

const STATUS = {
  questions: "Writing a few questions", answering: "Waiting for your answers", planning: "Planning",
  review: "Plan ready to review", building: "Writing sessions", ready: "",
};

// what this person typed and picked, kept while they move around the app (not saved)
const filter = { q: "", tag: "" };

export default async function home(view, scope) {
  const courses = await api("/api/courses");
  let feedHtml = "";
  const paintFeed = () => {
    const box = view.querySelector("#feedbox");
    if (box && feedHtml) { box.innerHTML = feedHtml; box.hidden = false; }
  };
  const draw = (courses) => {
    const mine = courses.filter((c) => c.mine).sort((a, b) => (b.pinned - a.pinned)
      || String(b.last_opened_at || b.created_at).localeCompare(String(a.last_opened_at || a.created_at)));
    const going = mine.find((c) => c.progress.next && c.progress.done < c.progress.sessions);
    view.innerHTML = html`
      <div class="hero"><span class="iso" aria-hidden="true"></span>
        <div><div class="eyebrow">self-paced learning</div><h1>Your courses<br><span class="tone2">learn anything, at your own pace.</span></h1><p>No deadlines, no grades: just progress.</p></div>
        <div class="row">${raw(can("author") ? html`<a class="button ghost" href="#/import">${raw(icon("upload", 15))}Import</a>
          <a class="button" href="#/new">${raw(icon("plus", 15))}New course</a>` : "")}</div>
      </div>
      ${raw(going ? html`<div class="panel continue">
        <div><div class="small muted">Continue where you left off</div><h2>${going.title}</h2>
          <div class="small muted">${going.progress.done} of ${going.progress.sessions} sessions done${raw(going.progress.due_reviews && !going.reading_mode
            ? html` · ${going.progress.due_reviews} to revisit in the next warm-up` : "")}</div></div>
        <a class="button" href="#/session/${going.progress.next}">Continue${raw(icon("chevron-right", 15))}</a></div>` : "")}
      ${raw(courses.length ? html`<div class="library"><div class="library-tools">
          <label class="search">${raw(icon("search", 15))}<input type="search" id="q" placeholder="Search courses" aria-label="Search courses" value="${filter.q}"></label>
          <div class="tagbar" id="tags" role="group" aria-label="Filter by tag"></div>
        </div>
        <section class="shelf" aria-labelledby="mine-h">
          <div class="shelf-head"><h2 id="mine-h">My courses</h2><span class="small faint" id="mine-n"></span></div>
          <div class="grid" id="mine"></div>
        </section>
        <section class="shelf available" aria-labelledby="all-h">
          <div class="shelf-head"><h2 id="all-h">Available</h2><span class="small faint" id="all-n"></span></div>
          <p class="small muted shelf-hint">Open one to look around. It moves up to your courses once you start it, or add it with ${raw(icon("plus", 12))}.</p>
          <div class="grid" id="all"></div>
        </section><section class="shelf" id="feedbox" hidden></section></div>` : html`
        <div class="panel empty"><div class="big">What do you want to learn?</div>
          <p class="muted">Name any subject, pick how deep to go, and the AI writes you a course.</p>
          ${raw(can("author") ? `<a class="button" href="#/new">${icon("plus", 15)}Start your first course</a>` : `<p class="small faint">When an author publishes a course, it shows up here.</p>`)}</div>`)}`;
    if (!courses.length) return;
    const others = courses.filter((c) => !c.mine);
    const tags = [...new Set(courses.flatMap((c) => c.tags))].sort();
    const paint = () => {
      const q = filter.q.trim().toLowerCase();
      const hit = (c) => (!filter.tag || c.tags.includes(filter.tag))
        && (!q || [c.title, c.subject, c.summary, ...c.tags].join(" ").toLowerCase().includes(q));
      const m = mine.filter(hit), a = others.filter(hit);
      const filtered = q || filter.tag;
      view.querySelector("#mine").innerHTML = m.length ? m.map(card).join("")
        : html`<div class="panel empty-shelf small muted">${filtered ? "None of your courses match." : "Nothing here yet. Start a course below, or pin one, and it stays up here."}</div>`;
      view.querySelector("#all").innerHTML = a.length ? a.map(card).join("")
        : html`<div class="panel empty-shelf small muted">${filtered ? "Nothing else matches." : "You've got every course. Nothing else to add."}</div>`;
      view.querySelector("#mine-n").textContent = filtered ? `${m.length} of ${mine.length}` : `${mine.length}`;
      view.querySelector("#all-n").textContent = filtered ? `${a.length} of ${others.length}` : `${others.length}`;
      view.querySelector("#tags").innerHTML = tags.length ? [["", "All"], ...tags.map((t) => [t, t])].map(([t, label]) =>
        html`<button class="chip ${filter.tag === t ? "on" : ""}" data-tag="${t}" aria-pressed="${filter.tag === t}">${raw(t ? icon("tag", 12) : "")}${label}</button>`).join("") : "";
    };
    paint();
    paintFeed();
    view.querySelector(".library").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-shelf]");
      if (!b) return;
      e.preventDefault();
      const [what, id] = [b.dataset.shelf, b.dataset.id];
      const json = what === "pin" ? { pinned: true } : what === "unpin" ? { pinned: false }
        : what === "add" ? { shelf: "mine" } : { shelf: "aside" };
      try {
        await api(`/api/courses/${id}/shelf`, { method: "PUT", json });
        toast({ pin: "Pinned to the top.", unpin: "Unpinned.", add: "Added to your courses.", aside: "Moved to available. Your progress is kept." }[what]);
        draw(await api("/api/courses"));
      } catch (err) { toast(err.message, true); }
    });
    view.querySelector("#q").addEventListener("input", (e) => { filter.q = e.target.value; paint(); });
    view.querySelector("#tags").addEventListener("click", (e) => {
      const b = e.target.closest("[data-tag]");
      if (!b) return;
      filter.tag = filter.tag === b.dataset.tag ? "" : b.dataset.tag;
      paint();
    });
  };
  draw(courses);
  if (team()) {
    api("/api/feed").then((f) => {
      if (!f.on || !f.items.length) return;
      feedHtml = html`<div class="shelf-head"><h2>Recently</h2><span class="small faint">from people who share their activity${raw(f.sharing ? "" : ' · <a href="#/account">share yours</a>')}</span></div>
        <ul class="feed panel">${f.items.slice(0, 8).map((x) => raw(feedLine(x)))}</ul>`;
      paintFeed();
    }).catch(() => {});
  }
  if (courses.some((c) => c.status !== "ready")) {
    scope.every(5000, async () => {
      if (document.activeElement && document.activeElement.id === "q") return true;   // don't redraw under someone typing
      const fresh = await api("/api/courses");
      draw(fresh);
      return fresh.some((c) => c.status !== "ready");
    });
  }
}

function actions(c) {
  const b = (what, ic, label) => html`<button class="icon-btn" data-shelf="${what}" data-id="${c.id}" title="${label}" aria-label="${label}: ${c.title}">${raw(icon(ic, 15))}</button>`;
  if (!c.mine) return b("add", "plus", "Add to my courses");
  return (c.pinned ? b("unpin", "pin-off", "Unpin") : b("pin", "pin", "Pin to the top")) + b("aside", "archive", "Move to available");
}

function card(c) {
  const p = c.progress;
  const share = p.sessions ? p.done / p.sessions : 0;
  const state = STATUS[c.status];
  return html`<div class="panel card${c.pinned ? " pinned" : ""}">
    <div class="spread"><span class="row" style="gap:6px">${raw(c.pinned ? `<span class="pill accent">${icon("pin", 11)}pinned</span>` : "")}<span class="pill">${c.depth_label}</span>${raw(c.visibility === "draft" && team()
      ? `<span class="pill teal">draft</span>` : "")}${raw(state && c.can_edit ? html`<span class="pill teal">${state}</span>` : "")}</span>
      <span class="card-actions">${raw(actions(c))}</span></div>
    <h3><a class="stretch" href="#/course/${c.id}">${c.title}</a></h3>
    <div class="sum">${c.summary || c.subject}</div>
    ${raw(c.tags.length ? html`<div class="tags">${c.tags.map((t) => raw(html`<span class="tag">${t}</span>`))}</div>` : "")}
    ${raw(team() && c.author ? html`<div class="small faint">by ${c.author}</div>` : "")}
    ${raw(c.error ? html`<div class="small" style="color:var(--bad)">Needs attention: ${c.error}</div>` : "")}
    ${raw(p.sessions ? html`<div class="bar"><span style="width:${Math.round(share * 100)}%"></span></div>` : "")}
    <div class="foot"><span>${p.sessions ? `${p.done} / ${p.sessions} sessions` : ""}</span>
      <span>${raw(c.reading_mode ? `${icon("book-open", 12)} Reading mode` : p.due_reviews ? `${icon("refresh-cw", 12)} ${p.due_reviews} to revisit`
        : ago(c.last_opened_at || c.created_at))}</span></div>
  </div>`;
}
