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
  </div>`;
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
