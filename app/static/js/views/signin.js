// Sign-in, and choosing a new password (required after an admin creates or resets an account).
import { $, act, api, html, raw, team, who } from "../util.js";
import { icon } from "../icons.js";

export async function signin(view, { onDone }) {
  const personal = !team();
  view.innerHTML = html`<div class="auth-card">
    <div class="eyebrow">${personal ? "this knwlge is protected" : "welcome back"}</div>
    <h1>Sign in<br><span class="tone2">${personal ? "with your password." : "to keep learning."}</span></h1>
    ${raw(who.setup_needed ? html`<div class="note warn small">No admin account exists yet. Whoever runs the server can create one with
      <code>python -m app.accounts add-admin &lt;username&gt;</code> (see the README).</div>` : "")}
    <form id="f" class="stack" autocomplete="on">
      ${raw(personal ? "" : html`<div><label class="field" for="u">Username</label>
        <input type="text" id="u" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required></div>`)}
      <div><label class="field" for="p">Password</label>
        <input type="password" id="p" name="password" autocomplete="current-password" required></div>
      <div class="row"><button type="submit" id="go">${raw(icon("log-in", 15))}sign in</button></div>
      ${raw(personal ? "" : `<p class="small faint">Forgot your password? Ask an admin to reset it.</p>`)}
    </form></div>`;
  (personal ? $("#p", view) : $("#u", view)).focus();
  $("#f", view).addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#go", view), async () => {
      await api("/api/auth/login", { method: "POST", json: { username: personal ? "" : $("#u", view).value, password: $("#p", view).value } });
      await onDone();
    });
  });
}

export async function password(view, { forced, onDone }) {
  view.innerHTML = html`<div class="auth-card">
    <div class="eyebrow">${forced ? "first sign-in" : "your account"}</div>
    <h1>Choose a password<br><span class="tone2">${forced ? "only you will know." : "to replace the old one."}</span></h1>
    ${raw(forced ? `<p class="muted">The password you were given only works once. Pick your own to continue.</p>` : "")}
    <form id="f" class="stack" autocomplete="on">
      <input type="text" name="username" autocomplete="username" value="${who.user ? who.user.username : ""}" hidden>
      <div><label class="field" for="cur">${forced ? "The password you were given" : "Current password"}</label>
        <input type="password" id="cur" autocomplete="current-password" required></div>
      <div><label class="field" for="n1">New password</label>
        <div class="field-hint">At least 10 characters. A few random words work well.</div>
        <input type="password" id="n1" autocomplete="new-password" minlength="10" required></div>
      <div><label class="field" for="n2">New password again</label>
        <input type="password" id="n2" autocomplete="new-password" minlength="10" required></div>
      <div class="row"><button type="submit" id="go">save password</button>
        ${raw(forced ? "" : `<a href="#/">cancel</a>`)}</div>
    </form></div>`;
  $("#cur", view).focus();
  $("#f", view).addEventListener("submit", (e) => {
    e.preventDefault();
    act($("#go", view), async () => {
      if ($("#n1", view).value !== $("#n2", view).value) throw new Error("The two new passwords don't match.");
      await api("/api/auth/password", { method: "POST", json: { current: $("#cur", view).value, new: $("#n1", view).value } });
      if (who.user) who.user.must_change = false;
      await onDone();
    });
  });
}
