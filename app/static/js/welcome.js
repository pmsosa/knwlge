// The welcome a person sees once (an admin can change its words), and asking for it again from the account page.
import { api, html, raw, who } from "./util.js";
import { md } from "./md.js";
import { icon } from "./icons.js";
import { dialog } from "./review.js";

export function showWelcome(text = who.welcome) {
  who.welcome = null;
  const d = dialog(html`<dialog class="modal welcome" aria-label="Welcome">
    <div class="modal-body">
      <div class="prose">${raw(md(text || ""))}</div>
      ${raw(who.upload_note ? html`<div class="note small">${raw(icon("shield-alert", 15))} ${who.upload_note}</div>` : "")}
      <div class="row modal-actions"><span style="flex:1"></span>
        <button type="button" data-close autofocus>${raw(icon("check", 15))}Got it</button></div></div></dialog>`);
  d.addEventListener("close", () => { api("/api/me/welcomed", { method: "POST", json: {} }).catch(() => {}); });
  return d;
}

export async function welcomeAgain() {
  const r = await api("/api/me/welcomed", { method: "POST", json: { seen: false } });
  showWelcome(r.welcome);
}

