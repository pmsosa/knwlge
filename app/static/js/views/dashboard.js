// Admins only (team mode): who is taking what, where people get stuck, what it costs, and the opt-in feed.
import { $, act, ago, api, html, raw, money, toast } from "../util.js";
import { icon } from "../icons.js";
import { feedLine } from "../feed.js";

export default async function dashboard(view) {
  const d = await api("/api/dashboard");
  const t = d.totals;
  const busiest = d.courses.filter((c) => c.takers).sort((a, b) => b.takers - a.takers);
  view.innerHTML = html`<h1>Dashboard</h1>
    <p class="muted">Who is learning what, and where people get stuck. Progress only, never scores.</p>
    <div class="grid stats-grid">
      <div class="panel"><div class="small muted">People</div><div class="big-number">${t.people}</div><div class="small muted">with an active account</div></div>
      <div class="panel"><div class="small muted">Learning now</div><div class="big-number">${t.learning}</div><div class="small muted">with a course in progress</div></div>
      <div class="panel"><div class="small muted">Courses finished</div><div class="big-number">${t.finished}</div><div class="small muted">by everyone, all time</div></div>
      <div class="panel"><div class="small muted">AI spend this month</div><div class="big-number">${money(d.spend.month)}</div>
        <div class="small muted">${d.spend.cap ? `of a ${money(d.spend.cap)} budget` : "no monthly budget"} · <a href="#/usage">details</a></div></div>
    </div>

    <div class="panel"><h2>People</h2>
      <table class="kv dash"><thead><tr><th>Person</th><th>Taking</th><th>Finished</th><th>Achievements</th><th>Last active</th></tr></thead><tbody>
      ${d.people.filter((p) => p.active).map((p) => raw(html`<tr><td><b>${p.name}</b> <span class="small faint">${p.role}</span></td>
        <td>${raw(p.courses.length ? p.courses.slice(0, 4).map((c) => html`<div class="small"><a href="#/course/${c.id}">${c.title}</a>
          <span class="faint">${c.done}/${c.sessions}</span></div>`).join("") + (p.courses.length > 4 ? html`<div class="small faint">and ${p.courses.length - 4} more</div>` : "")
          : `<span class="small faint">Nothing started</span>`)}</td>
        <td>${p.finished}</td><td>${p.achievements}</td><td class="small">${p.last_seen_at ? ago(p.last_seen_at) : "never"}</td></tr>`))}
      </tbody></table></div>

    <div class="panel"><h2>Courses</h2>
      ${raw(busiest.length ? busiest.map((c) => html`<div class="dash-course">
        <div class="spread"><a href="#/course/${c.id}"><b>${c.title}</b></a>
          <span class="small muted">${c.takers} taking · ${c.finished} finished · ${money(c.spend_month)} this month</span></div>
        <div class="funnel" role="img" aria-label="${`How many people finished each session of ${c.title}`}">${raw(c.funnel.map((s) => html`<span title="${`Session ${s.seq}: ${s.title}. ${s.done} finished`}"
          style="height:${Math.max(4, Math.round((s.done / Math.max(1, c.takers)) * 44))}px"></span>`).join(""))}</div>
        ${raw(c.stuck.length ? html`<div class="small" style="margin-top:6px">${raw(icon("circle-alert", 13))} Often missed or revealed:
          ${c.stuck.map((s) => `session ${s.seq} (${s.missed} missed, ${s.revealed} revealed of ${s.answers})`).join("; ")}</div>` : "")}
      </div>`).join("") : `<p class="muted">Nobody has started a course yet.</p>`)}
      ${raw(d.courses.filter((c) => !c.takers).length ? html`<p class="small faint">Not started by anyone yet: ${d.courses.filter((c) => !c.takers).map((c) => c.title).join(", ")}</p>` : "")}
    </div>

    <div class="grid two">
      <div class="panel"><h2>Spend by provider, this month</h2>
        ${raw(d.spend.by_provider.length ? html`<table class="kv"><tbody>${d.spend.by_provider.map((r) => raw(html`<tr><td>${r.label}</td><td>${r.calls} calls</td><td>${money(r.cost)}</td></tr>`))}</tbody></table>`
          : `<p class="muted small">Nothing yet this month.</p>`)}
        ${raw(d.spend.by_user.length ? html`<h3>By person</h3><table class="kv"><tbody>${d.spend.by_user.map((r) => raw(html`<tr><td>${r.name}</td><td>${r.calls} calls</td><td>${money(r.cost)}</td></tr>`))}</tbody></table>` : "")}
      </div>
      <div class="panel"><div class="spread"><h2 style="margin:0">Activity feed</h2>
        <label class="row small" style="gap:6px"><input type="checkbox" id="feedon" ${raw(d.feed.on ? "checked" : "")}> On for everyone</label></div>
        <p class="small muted">Each person chooses whether they appear (off by default, in their account).
          ${d.people.filter((p) => p.sharing).length} of ${t.people} share.</p>
        ${raw(d.feed.on ? (d.feed.items.length ? html`<ul class="feed">${d.feed.items.map((f) => raw(feedLine(f)))}</ul>` : `<p class="muted small">Nothing shared yet.</p>`)
          : `<p class="muted small">The feed is off: nothing is recorded or shown.</p>`)}
      </div>
    </div>`;
  $("#feedon", view).addEventListener("change", (e) => act(e.target, async () => {
    await api("/api/feed/switch", { method: "PUT", json: { on: e.target.checked } });
    toast(e.target.checked ? "The feed is on. People still choose whether they appear." : "The feed is off.");
    await dashboard(view);
  }));
}
