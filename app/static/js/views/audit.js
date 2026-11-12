// Admins: the audit log, with filters and CSV export.
import { $, act, api, html, raw, toast } from "../util.js";
import { icon } from "../icons.js";

const LABEL = {
  "auth.signin": "Signed in", "auth.signin_failed": "Failed sign-in", "user.created": "Account created",
  "user.updated": "Account changed", "user.password_reset": "Password reset", "user.password_changed": "Changed own password",
  "user.claimed_owner": "Became the first admin", "user.renamed_self": "Changed own name", "course.created": "Course created", "course.plan_approved": "Plan approved",
  "course.plan_changes_requested": "Plan changes asked for", "course.published": "Course published",
  "course.unpublished": "Course unpublished", "course.deleted": "Course deleted", "course.renamed": "Course renamed",
  "course.options": "Course extras changed", "course.exported": "Course exported", "session.regenerated": "Session rewritten",
  "session.chunk_edited": "Lesson part edited",
  "session.chunk_revise_asked": "Lesson part rewrite asked for", "session.chunk_revised": "Lesson part rewritten by Gemini", "item.edited": "Question edited", "item.deleted": "Question deleted",
  "material.added": "Material added", "material.removed": "Material removed", "settings.key_changed": "AI key changed",
  "settings.key_removed": "AI key removed", "settings.models": "Models changed", "settings.budget": "Budget changed",
  "settings.personal_password_set": "Password turned on", "settings.personal_password_removed": "Password turned off",
  "audit.exported": "Audit log exported", "audit.pruned": "Audit log pruned",
};

function summary(r) {
  const d = r.details || {};
  if (d.before !== undefined && d.after !== undefined) return "before and after kept";
  return Object.entries(d).filter(([k]) => !["course"].includes(k)).slice(0, 4)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ").slice(0, 160);
}

export default async function auditView(view) {
  const filters = { who: "", action: "", target: "", since: "", until: "" };
  view.innerHTML = html`
    <div class="spread" style="margin-bottom:14px"><h1 style="margin:0">Audit <span class="tone2">who did what, when.</span></h1></div>
    <form class="panel row" id="f" style="align-items:flex-end">
      <div><label class="field" for="who">Person</label><input type="text" id="who" placeholder="username" style="width:150px"></div>
      <div><label class="field" for="action">Action</label><input type="text" id="action" placeholder="e.g. course." style="width:150px"></div>
      <div><label class="field" for="target">Course or item id</label><input type="text" id="target" style="width:200px"></div>
      <div><label class="field" for="since">From</label><input type="text" id="since" placeholder="2026-11-01" style="width:120px"></div>
      <div><label class="field" for="until">Before</label><input type="text" id="until" placeholder="2026-12-01" style="width:120px"></div>
      <button type="submit" class="ghost">${raw(icon("search", 15))}filter</button><a class="button ghost" id="csv" href="/api/audit.csv">${raw(icon("download", 15))}export CSV</a>
    </form>
    <div class="panel" style="padding:0;overflow:hidden;margin-top:12px"><table class="kv"><thead><tr><th>When</th><th>Who</th><th>What</th>
      <th>On</th><th>Details</th></tr></thead><tbody id="rows"></tbody></table></div>
    <details class="small" style="margin-top:14px"><summary>Prune old entries</summary>
      <div class="row" style="margin-top:8px"><input type="text" id="before" placeholder="remove entries before 2026-01-01" style="width:260px">
        <button class="danger small" id="prune">${raw(icon("trash-2", 14))}prune</button></div></details>`;
  const load = async () => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    $("#csv", view).href = `/api/audit.csv?${q}`;
    const rows = await api(`/api/audit?${q}`);
    $("#rows", view).innerHTML = rows.length ? rows.map((r) => html`<tr>
      <td class="small" style="white-space:nowrap">${new Date(r.at).toLocaleString()}</td>
      <td class="small">${r.display_name || r.username || "—"}</td>
      <td>${LABEL[r.action] || r.action}${raw(r.cost_usd != null ? html` <span class="pill">$${r.cost_usd.toFixed(3)}</span>` : "")}</td>
      <td class="small faint">${r.target_type ? `${r.target_type} ${r.target_id}` : ""}</td>
      <td class="small faint">${summary(r)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="muted">Nothing matches.</td></tr>`;
  };
  $("#f", view).addEventListener("submit", (e) => {
    e.preventDefault();
    for (const k of Object.keys(filters)) filters[k] = $(`#${k}`, view).value.trim();
    act(null, load);
  });
  $("#prune", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const before = $("#before", view).value.trim();
    if (!before || !confirm(`Remove every audit entry before ${before}? This can't be undone.`)) return;
    const r = await api("/api/audit/prune", { method: "POST", json: { before } });
    toast(`Removed ${r.removed} entries.`);
    await load();
  }));
  await load();
}
