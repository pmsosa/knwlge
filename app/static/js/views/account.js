// Your own account: the name others see, and (where there is one) your password.
import { $, act, api, html, raw, team, toast, who } from "../util.js";
import { icon } from "../icons.js";

export default async function account(view) {
  const u = who.user;
  const hasPassword = who.needs_signin;   // team mode, or personal mode with a password set
  view.innerHTML = html`<div class="auth-card">
    <div class="eyebrow">your account</div>
    <h1>${u.display_name}<br><span class="tone2">${team() ? `${u.role} · ${u.username}` : "just you"}</span></h1>
    <form id="f" class="stack" autocomplete="off">
      <div><label class="field" for="dn">Your name</label>
        <div class="field-hint">${team() ? "Shown at the top of the page, on courses you write and in the audit log." : "Shown at the top of the page."}</div>
        <input type="text" id="dn" maxlength="80" value="${u.display_name}" required autocomplete="name"></div>
      <div class="row"><button type="submit" id="go">${raw(icon("check", 15))}save name</button></div>
    </form>
    ${raw(hasPassword ? html`<hr><div class="row"><a class="button ghost" href="#/password">${raw(icon("key-round", 15))}change password</a></div>` : "")}
    <div id="share"></div>
    <hr><h2>Your achievements</h2><div id="achs"><p class="muted small">Loading…</p></div>
  </div>`;
  if (team()) {
    api("/api/feed").then((f) => {
      const box = $("#share", view);
      if (!box || !f.on) return;
      box.innerHTML = html`<hr><h2>Activity feed</h2>
        <p class="small muted">When it's on, people here see when you finish a session or a course, or earn an achievement.
          Nothing you did before turning it on is shown, and turning it off takes your entries off the feed.</p>
        <label class="row" style="gap:8px"><input type="checkbox" id="sharing" ${raw(f.sharing ? "checked" : "")}> Share my activity</label>`;
      $("#sharing", box).addEventListener("change", async (e) => {
        try {
          await api("/api/me/sharing", { method: "PUT", json: { on: e.target.checked } });
          toast(e.target.checked ? "Your activity is shared from now on." : "Not shared. Your entries are off the feed.");
        } catch (err) { toast(err.message, true); e.target.checked = !e.target.checked; }
      });
    }).catch(() => {});
  }
  api("/api/me/achievements").then((list) => {
    const box = $("#achs", view);
    if (!box) return;
    box.innerHTML = list.length ? html`<ul class="achs">${list.map((a) => raw(html`<li class="ach got"><span class="ach-icon">${raw(icon(a.icon, 20))}</span>
      <div><b>${a.title}</b><div class="small muted">${a.description}</div>
        <div class="small faint"><a href="#/course/${a.course_id}">${a.course_title}</a> · ${new Date(a.earned_at).toLocaleDateString()}</div></div></li>`))}</ul>`
      : `<p class="muted small">None yet. Finish a session and your first one arrives.</p>`;
  }).catch(() => {});
  $("#f", view).addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#go", view), async () => {
      const r = await api("/api/me", { method: "PUT", json: { display_name: $("#dn", view).value } });
      who.user = r.user;
      document.dispatchEvent(new CustomEvent("knwlge:who"));
      toast("Saved.");
      await account(view);
    });
  });
}
