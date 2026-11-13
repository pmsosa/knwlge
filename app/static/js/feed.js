// One line of the opt-in activity feed.
import { ago, html, raw } from "./util.js";
import { icon } from "./icons.js";

export function feedLine(f) {
  const course = f.course_id ? html`<a href="#/course/${f.course_id}">${f.course_title}</a>` : "";
  const who = f.me ? "You" : f.who;
  let what;
  if (f.kind === "session_done") what = html`finished session ${f.details.seq} of ${raw(course)}`;
  else if (f.kind === "course_done") what = html`completed ${raw(course)}`;
  else what = html`earned <b>${f.details.title}</b> in ${raw(course)}`;
  const ic = f.kind === "achievement" ? "award" : f.kind === "course_done" ? "trophy" : "check";
  return html`<li>${raw(icon(ic, 14))}<span><b>${who}</b> ${raw(what)} <span class="faint small">${ago(f.at)}</span></span></li>`;
}
