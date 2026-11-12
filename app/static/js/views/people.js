// Admins: accounts, roles, first passwords and resets.
import { $, $$, act, ago, api, html, raw, toast, who } from "../util.js";
import { icon } from "../icons.js";

const ROLES = [["learner", "Learner", "takes published courses"], ["author", "Author", "also writes and publishes courses"],
  ["admin", "Admin", "also manages people, settings, spend and the audit log"]];

function passwordNote(name, pw) {
  return html`<div class="note small" style="margin-top:10px"><b>First password for ${name}:</b>
    <code style="user-select:all">${pw}</code><br>
    Give it to them privately. It's shown only now; they'll choose their own at first sign-in.</div>`;
}

export default async function people(view) {
  const users = await api("/api/users");
  view.innerHTML = html`
    <div class="spread" style="margin-bottom:14px"><h1 style="margin:0">People <span class="tone2">who learns and who writes.</span></h1></div>
    <div class="new-grid">
      <div class="panel" style="padding:0;overflow:hidden">
        <table class="kv people"><thead><tr><th>Person</th><th>Role</th><th>Last seen</th><th></th></tr></thead>
        <tbody>${users.map((u) => raw(html`<tr data-id="${u.id}" class="${u.active ? "" : "off"}">
          <td><b>${u.display_name}</b><div class="small faint">${u.username}${raw(u.id === who.user.id ? " · you" : "")}${raw(!u.has_password ? " · no password yet" : "")}</div></td>
          <td><select data-role aria-label="Role for ${u.username}" ${raw(u.id === who.user.id ? "disabled" : "")}>${ROLES.map(([k, l]) =>
            raw(html`<option value="${k}" ${raw(k === u.role ? "selected" : "")}>${l}</option>`))}</select></td>
          <td class="small faint">${u.active ? (u.last_seen_at ? ago(u.last_seen_at) : "never") : "deactivated"}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="ghost small" data-reset>${raw(icon("key-round", 14))}reset password</button>
            ${raw(u.id === who.user.id ? "" : html`<button class="ghost small" data-active>${raw(icon(u.active ? "user-x" : "user-check", 14))}<span>${u.active ? "deactivate" : "reactivate"}</span></button>`)}</td>
        </tr>`))}</tbody></table>
        <div id="out" style="padding:0 14px 14px"></div>
      </div>
      <form class="panel stack" id="add" autocomplete="off">
        <h2 style="margin:0">Add someone</h2>
        <div><label class="field" for="un">Username</label><input type="text" id="un" required autocapitalize="none" spellcheck="false"
          placeholder="e.g. alex or alex@example.com"></div>
        <div><label class="field" for="dn">Display name</label><input type="text" id="dn" placeholder="Alex Example"></div>
        <div><label class="field">Role</label>
          ${ROLES.map(([k, l, d]) => raw(html`<label class="row small" style="margin:4px 0"><input type="radio" name="role" value="${k}" ${raw(k === "learner" ? "checked" : "")}>
            <span><b>${l}</b> <span class="faint">${d}</span></span></label>`))}</div>
        <div><label class="field" for="pw">First password <span class="faint small">(optional)</span></label>
          <div class="field-hint">Leave empty and Knwlge makes one. Either way they must change it at first sign-in.</div>
          <input type="text" id="pw" autocomplete="off" spellcheck="false" placeholder="generate one for me"></div>
        <div class="row"><button type="submit" id="go">${raw(icon("plus", 15))}add person</button></div>
        <div id="added"></div>
      </form>
    </div>`;

  $("#add", view).addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#go", view), async () => {
      const name = $("#un", view).value.trim();
      const r = await api("/api/users", { method: "POST", json: {
        username: name, display_name: $("#dn", view).value.trim(), role: view.querySelector('input[name="role"]:checked').value,
        password: $("#pw", view).value || null } });
      await people(view);
      $("#added", view).innerHTML = passwordNote(name, r.password);
    });
  });
  $$("tr[data-id]", view).forEach((tr) => {
    const id = Number(tr.dataset.id);
    const name = tr.querySelector("b").textContent;
    tr.querySelector("[data-role]").addEventListener("change", (e) => act(null, async () => {
      try {
        await api(`/api/users/${id}`, { method: "PUT", json: { role: e.target.value } });
        toast(`${name} is now ${e.target.value === "admin" ? "an" : "a"} ${e.target.value}.`);
      } catch (err) { await people(view); throw err; }
    }));
    tr.querySelector("[data-reset]").addEventListener("click", (e) => act(e.currentTarget, async () => {
      if (!confirm(`Reset ${name}'s password? They'll be signed out everywhere and need the new one-time password.`)) return;
      const r = await api(`/api/users/${id}/reset-password`, { method: "POST", json: {} });
      $("#out", view).innerHTML = passwordNote(name, r.password);
    }));
    tr.querySelector("[data-active]")?.addEventListener("click", (e) => act(e.currentTarget, async () => {
      const off = e.currentTarget.textContent.trim() === "deactivate";
      if (off && !confirm(`Deactivate ${name}? They're signed out and can't sign in until reactivated. Their progress is kept.`)) return;
      await api(`/api/users/${id}`, { method: "PUT", json: { active: !off } });
      await people(view);
    }));
  });
}
