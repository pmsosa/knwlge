// A whole course on one page, laid out for paper: the browser's Print turns it into a PDF.
import { $, api, html, raw } from "../util.js";
import { icon } from "../icons.js";
import { md } from "../md.js";
import { enhance, renderMedia } from "../media.js";

const STATIC = ["image", "illustration", "svg", "mermaid"];   // what can go on paper as it is

export default async function printView(view, scope, id) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const answers = params.get("answers") === "1";
  const c = await api(`/api/courses/${id}/print${answers ? "?answers=1" : ""}`);
  view.classList.add("printing");
  const fig = (m) => {
    if (m.status !== "ready") return "";
    if (STATIC.includes(m.kind)) return renderMedia(m).outerHTML;
    const what = { video: "a video", audio: "a recording", widget: "an interactive exercise", experiment: "an interactive experiment" }[m.kind] || "media";
    return html`<p class="print-note">${raw(icon("external-link", 12))} Here the course has ${what}${m.caption ? `: ${m.caption}` : ""}. Open it in Knwlge.</p>`;
  };
  const question = (i, n) => html`<li class="print-q"><div>${raw(md(i.prompt))}</div>
    ${raw(i.options.length ? html`<ul class="print-opts">${i.options.map((o) => raw(html`<li>${raw(md(o, { inline: true }))}</li>`))}</ul>` : "")}
    ${raw(i.qtype === "long" || i.qtype === "short" ? `<div class="print-lines" aria-hidden="true"></div>` : "")}
    ${raw(i.answer !== undefined ? html`<div class="print-answer"><b>Answer:</b> ${raw(md(i.answer, { inline: i.qtype !== "long" }))}
      ${raw(i.explanation ? html`<div class="small">${raw(md(i.explanation))}</div>` : "")}</div>` : "")}</li>`;
  const session = (s) => {
    const k = s.content || {};
    const checks = (ci) => s.items.filter((i) => i.section === "check" && i.chunk === ci);
    const rest = (sec) => s.items.filter((i) => i.section === sec);
    return html`<section class="print-session">
      <div class="eyebrow">Session ${s.seq} · ${s.kind_label} · about ${s.minutes} min</div>
      <h2>${s.title}</h2>
      ${raw(k.goal ? html`<p class="goal"><b>Goal:</b> ${k.goal}</p>` : "")}
      ${raw(k.hook ? md(k.hook) : "")}${raw(k.intro_markdown ? md(k.intro_markdown) : "")}
      ${(k.chunks || []).map((ch, ci) => raw(html`<h3>${ch.title}</h3>${raw(md(ch.markdown))}
        ${raw(s.media.filter((m) => m.chunk === ci).map(fig).join(""))}
        ${raw(ch.example_markdown ? html`<div class="print-example"><b>Example</b>${raw(md(ch.example_markdown))}</div>` : "")}
        ${raw(checks(ci).length ? html`<div class="print-checks"><b>Check yourself</b><ol>${checks(ci).map((i) => raw(question(i)))}</ol></div>` : "")}`))}
      ${raw(k.tips_markdown ? html`<h3>Tips</h3>${raw(md(k.tips_markdown))}` : "")}
      ${raw(rest("practice").length ? html`<h3>Practice</h3><ol>${rest("practice").map((i) => raw(question(i)))}</ol>` : "")}
      ${raw(rest("exercise").length ? html`<h3>Written exercise</h3><ol>${rest("exercise").map((i) => raw(html`<li><b>${i.title}</b>${raw(question(i).replace(/^<li class="print-q">|<\/li>$/g, ""))}</li>`))}</ol>` : "")}
      ${raw(rest("project").length ? html`<h3>Project options</h3><ol>${rest("project").map((i) => raw(html`<li><b>${i.title}</b>${raw(md(i.prompt))}</li>`))}</ol>` : "")}
      ${raw(k.wrapup && k.wrapup.key_points.length ? html`<h3>Key points</h3><ul>${k.wrapup.key_points.map((p) => raw(html`<li>${raw(md(p, { inline: true }))}</li>`))}</ul>` : "")}
    </section>`;
  };
  view.innerHTML = html`<div class="print-bar no-print">
      <a href="#/course/${c.id}">${raw(icon("chevron-left", 15))}Back to the course</a>
      <label class="row small" style="gap:6px"><input type="checkbox" id="ans" ${raw(answers ? "checked" : "")}> Include answers${c.can_edit ? "" : " (to questions you've tried or revealed)"}</label>
      <button id="print">${raw(icon("printer", 15))}Print or save as PDF</button>
    </div>
    <article class="print-doc">
      <header class="print-cover"><div class="eyebrow">Knwlge · ${c.depth_label}</div><h1>${c.title}</h1><p class="summary">${c.summary}</p>
        ${raw(c.author ? html`<p class="small muted">by ${c.author}</p>` : "")}
        ${raw(c.prerequisites.length ? html`<p><b>Good to know first:</b> ${c.prerequisites.join("; ")}</p>` : "")}
        <ol class="print-toc">${c.sessions.map((s) => raw(html`<li>${s.title} <span class="muted small">(${s.kind_label})</span></li>`))}</ol></header>
      ${c.sessions.map((s) => raw(session(s)))}
      ${raw(c.reading.length ? html`<section class="print-session"><h2>Further reading</h2><ul>${c.reading.map((r) => raw(html`<li><b>${r.title}</b>${r.creator ? `, ${r.creator}` : ""} (${r.kind}${r.free ? "" : ", paid"})${raw(r.url ? html`<br><span class="small">${r.url}</span>` : "")}<div class="small">${r.why}</div></li>`))}</ul></section>` : "")}
    </article>`;
  enhance(view);
  $("#print", view).addEventListener("click", () => window.print());
  $("#ans", view).addEventListener("change", (e) => {
    location.hash = `#/print/${c.id}${e.target.checked ? "?answers=1" : ""}`;
  });
}
