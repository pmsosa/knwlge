// Your own account: the name others see, and (where there is one) your password.
import { $, act, ago, api, html, raw, team, toast, who } from "../util.js";
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
    <div id="myflags"></div>
  </div>`;
  api("/api/me/allowance").then((a) => {
    if (a.cap == null) return;
    const left = Math.max(0, a.cap - a.used);
    $("#share", view)?.insertAdjacentHTML("beforebegin", html`<hr><h2>This month's AI allowance</h2>
      <div class="bar" style="margin:6px 0"><span style="width:${Math.min(100, Math.round((a.used / a.cap) * 100))}%"></span></div>
      <p class="small muted">$${a.used.toFixed(2)} of $${a.cap.toFixed(2)} used${left ? "" : ": the tutor, feedback on written answers and your own courses wait until the 1st"}.
        Quick questions, reading and your progress don't use it.</p>`);
  }).catch(() => {});
  api("/api/me/flags").then(({ flags }) => {
    const box = $("#myflags", view);
    if (!box || !flags.length) return;
    const STATE = { checking: "being checked", open: "with the authors", fixing: "being fixed", fixed: "fixed", dismissed: "looked at: it's fine" };
    box.innerHTML = html`<hr><h2>Things you flagged</h2><p class="small muted">Thanks for these. Here's what happened to each.</p>
      <ul class="flags">${flags.map((f) => raw(html`<li class="flag"><div class="spread"><b>${raw(f.session_id ? html`<a href="#/session/${f.session_id}">${f.where}</a>` : f.where)}</b>
        <span class="pill ${f.status === "fixed" ? "good" : ""}">${STATE[f.status] || f.status}</span></div>
        <div class="small muted">${f.course_title} · ${ago(f.created_at)}</div>
        ${raw(f.note ? html`<div class="small">“${f.note}”</div>` : "")}
        ${raw(f.reply ? html`<div class="small"><b>Reply:</b> ${f.reply}</div>` : "")}</li>`))}</ul>`;
  }).catch(() => {});
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
