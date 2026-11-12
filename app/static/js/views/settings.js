import { $, act, api, html, raw, toast } from "../util.js";
import { icon } from "../icons.js";

const ROLES = [
  ["pro", "Planning and projects", "The best model: plans each course, checkpoints and projects."],
  ["flash", "Writing and feedback", "Writes most sessions, gives feedback, answers tutor questions, finds reading."],
  ["lite", "Quick checks", "Double-checks each session and marks short answers."],
  ["image", "Illustrations", "Draws AI illustrations for courses that have them switched on (no free tier)."],
];

export default async function settings(view) {
  const s = await api("/api/settings");
  const known = s.known_models.map((m) => m.id);
  const select = (role) => {
    const cur = s.models[role];
    const custom = !known.includes(cur);
    return html`<div class="row"><select data-role="${role}" style="max-width:24rem">
      ${s.known_models.map((m) => raw(html`<option value="${m.id}" ${raw(m.id === cur ? "selected" : "")}>${m.label}${m.id === s.defaults[role] ? " (default)" : ""}</option>`))}
      <option value="__custom" ${raw(custom ? "selected" : "")}>Another model id…</option></select>
      <input type="text" data-custom="${role}" value="${custom ? cur : ""}" placeholder="model id" style="max-width:16rem" ${raw(custom ? "" : "hidden")}></div>`;
  };
  let theme = "system";
  try { theme = localStorage.getItem("knwlge-theme") || "system"; } catch { /* private mode */ }
  view.innerHTML = html`<h1>Settings</h1>
    <div class="panel">
      <h2>Appearance</h2>
      <p class="muted small">Black on white, or white on black. "System" follows this device's light or dark setting. Saved on this device only.</p>
      <div class="row" role="radiogroup" aria-label="Theme">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) =>
        raw(html`<button class="small ${k === theme ? "" : "ghost"}" data-theme-pick="${k}" aria-pressed="${k === theme}">${l}</button>`))}</div>
    </div>
    <div class="panel stack">
      <div><h2>Gemini API key</h2>
        <p class="muted small">Get one at Google AI Studio. It's stored in Knwlge's database on this box and never sent to your browser.
          Grounded search (for reading lists) needs a paid-tier key.</p>
        <div class="row"><input type="password" id="key" autocomplete="off" placeholder="${s.key_hint ? `Saved (ends ${s.key_hint})` : "Paste your key"}" style="max-width:26rem">
          <button id="savekey">Save key</button>
          ${raw(s.key_hint ? `<button class="ghost" id="test">${icon("check", 15)}Test it</button><button class="link small" id="clearkey">Remove key</button>` : "")}</div>
        <p class="small" id="testres"></p></div>
    </div>
    <div class="panel stack">
      <div><h2>Monthly budget</h2>
        <p class="muted small">Optional. When this month's estimated Gemini spend reaches it, new work pauses until next month (or until you raise it).
          Work already running finishes, so it can go slightly over.</p>
        <div class="row"><span>$</span><input type="number" id="budget" min="0" step="1" value="${s.budget_monthly_usd ?? ""}" placeholder="No limit" style="max-width:9rem">
          <button class="ghost" id="savebudget">Save budget</button>
          ${raw(s.budget_monthly_usd ? `<button class="link small" id="clearbudget">No limit</button>` : "")}</div></div>
    </div>
    <div class="panel stack">
      <div><h2>Models</h2><p class="muted small">Change these if Google renames or retires a model. Prices for unlisted models aren't known, so their cost won't show in Usage.</p></div>
      ${ROLES.map(([role, title, hint]) => raw(html`<div><label class="field">${title}</label><div class="field-hint">${hint}</div>${raw(select(role))}</div>`))}
      <div><button class="ghost" id="savemodels">Save models</button></div>
    </div>
    ${raw(s.mode === "personal" ? html`<div class="panel stack" id="protect">
      <div><h2>Password</h2>
        <p class="muted small">${s.personal_password
          ? "Knwlge asks for a password before anyone can use it. Turn it off to make it open again."
          : "Knwlge is open: anyone who can reach this address can use it. Set a password to require signing in."}</p></div>
      ${raw(s.personal_password ? html`<div><label class="field" for="pcur">Current password</label>
        <input type="password" id="pcur" autocomplete="current-password" style="max-width:20rem"></div>` : "")}
      <div><label class="field" for="pnew">${s.personal_password ? "New password" : "Password"}</label>
        <div class="field-hint">At least 10 characters.</div>
        <input type="password" id="pnew" autocomplete="new-password" style="max-width:20rem"></div>
      <div class="row"><button id="psave">${s.personal_password ? "change password" : "turn on password"}</button>
        ${raw(s.personal_password ? `<button class="ghost" id="poff">turn off password</button>` : "")}</div>
    </div>` : "")}
    <div class="panel">
      <h2>Paused work</h2>
      <p class="muted small">Work pauses when Gemini rate-limits, refuses the key, or the budget is reached. Saving settings resumes it; so does this.</p>
      <button class="ghost" id="resume">${raw(icon("play", 15))}Resume paused work now</button>
    </div>`;

  $("#psave", view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    const r = await api("/api/personal/password", { method: "POST", json: { current: $("#pcur", view)?.value || "", new: $("#pnew", view).value } });
    toast(r.protected ? "Password saved. Knwlge will ask for it from now on." : "Saved.");
    settings(view);
  }));
  $("#poff", view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    if (!confirm("Turn off the password? Anyone who can reach this address will be able to use Knwlge.")) return;
    await api("/api/personal/password", { method: "POST", json: { current: $("#pcur", view).value, new: null } });
    toast("Password turned off.");
    settings(view);
  }));
  view.querySelectorAll("[data-theme-pick]").forEach((b) => b.addEventListener("click", () => {
    const pick = b.dataset.themePick;
    try { localStorage.setItem("knwlge-theme", pick); } catch { /* private mode */ }
    if (pick === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = pick;
    const dark = pick === "dark" || (pick === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#161615" : "#efefe4");
    view.querySelectorAll("[data-theme-pick]").forEach((x) => {
      x.classList.toggle("ghost", x !== b);
      x.setAttribute("aria-pressed", String(x === b));
    });
  }));
  view.querySelectorAll("select[data-role]").forEach((sel) => sel.addEventListener("change", () => {
    view.querySelector(`[data-custom="${sel.dataset.role}"]`).hidden = sel.value !== "__custom";
  }));
  $("#savekey", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const key = $("#key", view).value.trim();
    if (!key) throw new Error("Paste a key first.");
    await api("/api/settings", { method: "PUT", json: { api_key: key } });
    toast("Key saved.");
    settings(view);
  }));
  $("#clearkey", view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    if (!confirm("Remove the saved key? Course work pauses until you add one.")) return;
    await api("/api/settings", { method: "PUT", json: { clear_key: true } });
    settings(view);
  }));
  $("#test", view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    const out = $("#testres", view);
    out.textContent = "Asking Gemini…";
    const r = await api("/api/settings/test", { method: "POST" });
    out.innerHTML = r.ok ? html`<span style="color:var(--good)">✓ Works (${r.model}):</span> ${r.message}` : html`<span style="color:var(--bad)">${r.message}</span>`;
  }));
  $("#savebudget", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const v = $("#budget", view).value;
    await api("/api/settings", { method: "PUT", json: v === "" ? { clear_budget: true } : { budget_monthly_usd: Number(v) } });
    toast("Budget saved.");
    settings(view);
  }));
  $("#clearbudget", view)?.addEventListener("click", (e) => act(e.currentTarget, async () => {
    await api("/api/settings", { method: "PUT", json: { clear_budget: true } });
    settings(view);
  }));
  $("#savemodels", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const models = {};
    for (const [role] of ROLES) {
      const v = view.querySelector(`select[data-role="${role}"]`).value;
      models[role] = v === "__custom" ? view.querySelector(`[data-custom="${role}"]`).value.trim() : v;
    }
    await api("/api/settings", { method: "PUT", json: { models } });
    toast("Models saved.");
  }));
  $("#resume", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const r = await api("/api/jobs/resume", { method: "POST" });
    toast(r.resumed ? `Resumed ${r.resumed} paused step${r.resumed > 1 ? "s" : ""}.` : "Nothing was paused.");
  }));
}
