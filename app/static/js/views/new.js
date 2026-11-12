import { $, act, api, can, html, raw, team } from "../util.js";
import { icon } from "../icons.js";

export default async function newCourse(view) {
  const [tiers, extras] = await Promise.all([api("/api/tiers"), api("/api/extras")]);
  view.innerHTML = html`
    <div class="spread" style="margin-bottom:12px"><h1 style="margin:0">New course <span class="tone2">what shall we learn?</span></h1>
      <span class="small muted">Gemini asks a few questions, then shows you a plan before writing anything.</span></div>
    <form id="f" autocomplete="off" class="stack">
      <div class="new-grid">
        <div class="stack"><div class="panel stack">
          <div><label class="field" for="subject">What do you want to learn?</label>
            <input type="text" id="subject" maxlength="300" required placeholder="e.g. Medieval art, the physics of music, Rust for Python programmers"></div>
          <div><label class="field" for="notes">Anything else? <span class="muted small">(optional)</span></label>
            <div class="field-hint">What you already know, an angle you like, what you want to do with it.</div>
            <textarea id="notes" maxlength="4000" style="min-height:5rem" placeholder="I play guitar and want to understand why chords sound the way they do."></textarea></div>
          <div><label class="field">Your own material <span class="muted small">(optional)</span></label>
            <div class="field-hint">Notes, a textbook chapter, a syllabus. Gemini builds around them.</div>
            <input type="file" id="files" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.heic,.txt,.md,.csv,.json,.tex,.py,.html,.xml,.yaml,.yml"></div>
        </div>
      <div>
          <label class="field">How deep?</label>
          <div class="depths">${tiers.map((t) => raw(html`<label class="depth">
            <input type="radio" name="depth" value="${t.key}" ${raw(t.key === "bootcamp" ? "checked" : "")}>
            <span class="name">${t.label}</span>
            <span class="stats">${t.sessions} sessions · ${t.minutes} min · about ${t.hours} h</span>
            <span class="blurb">${t.blurb}</span>
          </label>`))}</div>
        </div>
        <div class="row"><button type="submit" id="go">${raw(icon("sparkles", 15))}Start</button>
          ${raw(can("admin") ? `<span class="small muted">Planning costs a few cents. Each AI illustration is about 3¢.</span>` : "")}
          ${raw(team() ? `<span class="small muted">It stays a draft only you can see until you publish it.</span>` : "")}</div>
        </div>
        <div>
          <label class="field">What can lessons include?</label>
          <div class="extras">${extras.map((x) => raw(html`<label class="extra"><input type="checkbox" name="extra" value="${x.key}" ${raw(x.default ? "checked" : "")}>
            <div><b>${x.label}</b><span>${x.hint}</span></div></label>`))}</div>
          <div class="field-hint" style="margin-top:6px">You can change these later on the course's Course tab.</div>
        </div>
      </div>
    </form>`;
  $("#subject", view).focus();
  $("#f", view).addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#go", view), async () => {
      const depth = view.querySelector('input[name="depth"]:checked').value;
      const options = Object.fromEntries([...view.querySelectorAll('input[name="extra"]')].map((c) => [c.value, c.checked]));
      const { id } = await api("/api/courses", { method: "POST", json: {
        subject: $("#subject", view).value, notes: $("#notes", view).value, depth, options } });
      const files = $("#files", view).files;
      if (files.length) {
        const form = new FormData();
        for (const f of files) form.append("files", f);
        await api(`/api/courses/${id}/materials`, { method: "POST", form });
      }
      location.hash = `#/course/${id}`;
    });
  });
}
