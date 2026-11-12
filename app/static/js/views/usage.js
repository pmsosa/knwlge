import { api, html, raw, money } from "../util.js";

const KIND = { questions: "Questions before planning", plan: "Plans", session: "Writing sessions", check: "Second read-through",
  reading: "Reading lists (with search)", mark: "Feedback on your answers", chat: "Tutor questions", test: "Key tests" };

export default async function usage(view) {
  const u = await api("/api/usage");
  const month = new Date(u.month_start).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const share = u.cap ? Math.min(1, u.month_spend / u.cap) : 0;
  view.innerHTML = html`<h1>Usage</h1>
    <p class="muted">What Knwlge has spent on Gemini, worked out from the tokens each call used and Google's prices.
      Your Google bill is the final word.</p>
    <div class="grid">
      <div class="panel"><div class="small muted">${month}</div><div class="big-number">${money(u.month_spend)}</div>
        ${raw(u.cap ? html`<div class="bar" style="margin:.5rem 0"><span style="width:${Math.round(share * 100)}%"></span></div>
          <div class="small ${u.over_cap ? "" : "muted"}" style="${u.over_cap ? "color:var(--bad)" : ""}">${u.over_cap
            ? "Budget reached: new work is paused until next month or until you raise it." : `of your ${money(u.cap)} monthly budget`}</div>`
          : html`<div class="small muted">No monthly budget set. <a href="#/settings">Set one</a></div>`)}</div>
      <div class="panel"><div class="small muted">All time</div><div class="big-number">${money(u.all_time)}</div>
        <div class="small muted">${u.searches} Google searches this month (5,000 free, then $14 per 1,000)</div></div>
    </div>
    ${raw(u.unknown_price_calls ? html`<div class="note warn" style="margin-top:1rem">${u.unknown_price_calls} call${u.unknown_price_calls > 1 ? "s" : ""} this month used a model Knwlge doesn't have a price for, so ${u.unknown_price_calls > 1 ? "they aren't" : "it isn't"} in the totals.</div>` : "")}
    <div class="panel" style="margin-top:1rem"><h2>By course, this month</h2>
      ${raw(u.by_course.length ? html`<table class="kv"><thead><tr><th>Course</th><th>Calls</th><th>Cost</th></tr></thead><tbody>
        ${u.by_course.map((r) => raw(html`<tr><td>${raw(r.course_id ? html`<a href="#/course/${r.course_id}">${r.title || r.course_id}</a>` : "Settings tests")}</td>
          <td>${r.calls}</td><td>${money(r.cost)}</td></tr>`))}</tbody></table>` : `<p class="muted">Nothing yet this month.</p>`)}</div>
    ${raw(u.by_user && u.by_user.length > 1 ? html`<div class="panel"><h2>By person, this month</h2><table class="kv"><tbody>${u.by_user.map((r) =>
      raw(html`<tr><td>${r.name}</td><td>${r.calls} calls</td><td>${money(r.cost)}</td></tr>`))}</tbody></table></div>` : "")}
    <div class="panel"><h2>By kind of work</h2>
      ${raw(u.by_kind.length ? html`<table class="kv"><tbody>${u.by_kind.map((r) => raw(html`<tr><td>${KIND[r.kind] || r.kind}</td><td>${r.calls} calls</td><td>${money(r.cost)}</td></tr>`))}</tbody></table>`
        : `<p class="muted">Nothing yet this month.</p>`)}</div>
    <p class="small faint">Prices as listed by Google on 9 November 2026, including the increases due on 1 December 2026 (Gemini 4 Argon) and 1 January 2027 (Gemini 3.8 Flash).</p>`;
}
