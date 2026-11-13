// Bring in a .knwlge course package (made by any Knwlge's "Download course package").
import { $, act, api, html, raw, team } from "../util.js";
import { icon } from "../icons.js";

export default async function importView(view) {
  view.innerHTML = html`<p class="crumbs"><a href="#/">Courses</a> › Import</p>
    <h1>Import a course</h1>
    <p class="muted">Pick a <b>.knwlge</b> package someone made with "Download course package". The whole course comes in:
      sessions, questions, pictures and the reading list. Nothing is sent to the AI provider.</p>
    <div class="panel stack">
      <div><label class="field" for="pf">Package</label><input type="file" id="pf" accept=".knwlge,.zip"></div>
      <label class="row small" style="gap:6px"><input type="checkbox" id="prog" checked> Bring in the progress and notes saved in it, as mine</label>
      <p class="small faint" style="margin:0">Packages are checked before anything is kept: drawings and experiments go through the same
        checks as new lessons, and reading links are looked up again. ${team() ? "It arrives as a draft: publish it when you're happy with it." : ""}</p>
      <div><button id="go">${raw(icon("upload", 15))}Import</button></div>
    </div>`;
  $("#go", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const f = $("#pf", view).files[0];
    if (!f) throw new Error("Pick a package first.");
    const form = new FormData();
    form.append("file", f);
    form.append("progress", $("#prog", view).checked ? "true" : "false");
    const r = await api("/api/import", { method: "POST", form });
    location.hash = `#/course/${r.id}`;
  }));
}
