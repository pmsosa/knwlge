// Recommending a published course to chosen people or everyone: a nudge on their home page, with no deadline.
import { $, $$, act, api, ago, html, raw, toast } from "./util.js";
import { icon } from "./icons.js";
import { dialog } from "./review.js";

export async function openRecommend(c) {
  const data = await api(`/api/courses/${c.id}/recommendations`);
  const d = dialog(html`<dialog class="modal" aria-label="Recommend this course">
    <form class="modal-body">
      <h2 style="margin:0">Recommend <span class="tone2">${c.title}.</span></h2>
      <p class="small muted" style="margin:0">It shows on their home page as a suggestion, until they start it or say not now. No deadline.</p>
      <label class="switch-row"><input type="checkbox" id="rall"><div><b>Everyone</b><div class="small muted">Everyone who signs in, now and later.</div></div></label>
      <div id="rpick"><label class="search">${raw(icon("search", 15))}<input type="search" id="rq" placeholder="Find people" aria-label="Find people"></label>
        <ul class="pick-list">${data.people.map((p) => raw(html`<li data-name="${p.name.toLowerCase()}"><label class="row" style="gap:8px">
          <input type="checkbox" value="${p.id}"> ${p.name} <span class="small faint">${p.role}</span></label></li>`))}</ul></div>
      <div><label class="field" for="rnote">A note (optional)</label>
        <input type="text" id="rnote" maxlength="300" placeholder="e.g. A good start before the workshop"></div>
      <div id="rlist"></div>
      <div class="row modal-actions"><span style="flex:1"></span><button type="button" class="ghost" data-close>close</button>
        <button type="submit" id="rgo">${raw(icon("thumbs-up", 15))}Recommend</button></div>
    </form></dialog>`);
  const list = (recs) => {
    $("#rlist", d).innerHTML = recs.length ? html`<h3 style="margin:.4rem 0 .2rem">Recommended to</h3><ul class="rec-list">${recs.map((r) => raw(html`<li class="spread">
      <span><b>${r.to}</b> <span class="small muted">by ${r.by}, ${ago(r.at)}${r.note ? ` · “${r.note}”` : ""}</span></span>
      ${raw(r.can_remove ? html`<button type="button" class="link small" data-unrec="${r.id}">take back</button>` : "")}</li>`))}</ul>` : "";
  };
  list(data.recommendations);
  $("#rall", d).addEventListener("change", (e) => { $("#rpick", d).hidden = e.target.checked; });
  $("#rq", d).addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$(".pick-list li", d).forEach((li) => { li.hidden = !!q && !li.dataset.name.includes(q); });
  });
  $("#rlist", d).addEventListener("click", (e) => {
    const b = e.target.closest("[data-unrec]");
    if (b) act(b, async () => list((await api(`/api/recommendations/${b.dataset.unrec}`, { method: "DELETE" })).recommendations));
  });
  $("form", d).addEventListener("submit", (e) => {
    e.preventDefault();
    const everyone = $("#rall", d).checked;
    const to = $$(".pick-list input:checked", d).map((x) => Number(x.value));
    act($("#rgo", d), async () => {
      const r = await api(`/api/courses/${c.id}/recommendations`, { method: "POST", json: { everyone, to, note: $("#rnote", d).value } });
      list(r.recommendations);
      $$(".pick-list input:checked", d).forEach((x) => { x.checked = false; });
      toast(everyone ? "Recommended to everyone." : `Recommended to ${r.added} ${r.added === 1 ? "person" : "people"}.`);
    });
  });
}
