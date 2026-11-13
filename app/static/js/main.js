import { $, $$, api, can, esc, html, newPollScope, raw, team, toast, who } from "./util.js";
import home from "./views/home.js";
import newCourse from "./views/new.js";
import course from "./views/course.js";
import session from "./views/session.js";
import usage from "./views/usage.js";
import settings from "./views/settings.js";
import { signin, password } from "./views/signin.js";
import people from "./views/people.js";
import auditView from "./views/audit.js";
import account from "./views/account.js";
import printView from "./views/print.js";
import importView from "./views/import.js";
import dashboard from "./views/dashboard.js";
import { enhance } from "./media.js";
import { removeTutor } from "./tutor.js";
import { icon, paintIcons } from "./icons.js";

// [pattern, view, nav item, minimum role, team mode only]
const routes = [
  [/^#?\/?$/, home, "home", "learner"],
  [/^#\/new$/, newCourse, "new", "author"],
  [/^#\/course\/([\w-]+)(?:\/(\w+))?$/, course, "home", "learner"],
  [/^#\/session\/([\w-]+)$/, session, "home", "learner"],
  [/^#\/usage$/, usage, "usage", "admin"],
  [/^#\/settings$/, settings, "settings", "admin"],
  [/^#\/people$/, people, "people", "admin", true],
  [/^#\/audit$/, auditView, "audit", "admin", true],
  [/^#\/account$/, account, "", "learner"],
  [/^#\/print\/([\w-]+)(?:\?answers=1)?$/, printView, "home", "learner"],
  [/^#\/import$/, importView, "home", "author"],
  [/^#\/dashboard$/, dashboard, "dashboard", "admin", true],
];

const view = document.getElementById("view");

async function refreshWho() {
  Object.assign(who, await api("/api/me"));
  // the nav shows only what this person can use (the server checks again on every request)
  const nav = $(".top nav");
  nav.hidden = !who.user;
  $$("a", nav).forEach((a) => {
    a.hidden = (a.dataset.min && !can(a.dataset.min)) || (a.hasAttribute("data-team") && !team());
  });
  $("#menubtn").hidden = !who.user;
  const box = $("#whoami");
  box.hidden = !who.user || !who.needs_signin;
  if (who.user && who.needs_signin) {
    box.innerHTML = html`<a class="who-name" href="#/account" title="Your name and password">${who.user.display_name}</a>${raw(team() ? html` <span class="pill">${who.user.role}</span>` : "")}
      <button class="link small signout" id="signout">${raw(icon("log-out", 15))}<span>sign out</span></button>`;
    $("#signout").addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      who.user = null;
      location.hash = "#/signin";
      await refreshWho();
      route();
    });
  }
}

async function route() {
  const hash = location.hash || "#/";
  const scope = newPollScope();
  removeTutor();
  document.querySelector(".ctx-menu")?.remove();
  view.className = "";          // views that want the two-pane layout add "fill"
  view.scrollTop = 0;
  // signed out, or a new password needed: those screens only
  if (who.needs_signin && !who.user) {
    if (hash !== "#/signin") { location.hash = "#/signin"; return; }
    $$(".top nav a").forEach((a) => a.classList.remove("active"));
    return signin(view, { onDone: afterSignin });
  }
  if (who.user && who.user.must_change) {
    if (hash !== "#/password") { location.hash = "#/password"; return; }
    return password(view, { forced: true, onDone: afterSignin });
  }
  if (hash === "#/signin") { location.hash = "#/"; return; }
  if (hash === "#/password") return password(view, { forced: false, onDone: () => { location.hash = "#/"; } });
  const hit = routes.map(([re, fn, nav, min, teamOnly]) => [hash.match(re), fn, nav, min, teamOnly]).find(([m]) => m);
  $$(".top nav a").forEach((a) => a.classList.toggle("active", !!hit && a.dataset.nav === hit[2]));
  if (!hit || !can(hit[3]) || (hit[4] && !team())) {
    view.innerHTML = html`<div class="empty"><div class="big">Nothing here.</div><a href="#/">Back to your courses</a></div>`;
    return;
  }
  const [m, fn] = hit;
  view.innerHTML = `<p class="muted row"><span class="spinner"></span> Loading…</p>`;
  try {
    await fn(view, scope, ...m.slice(1));
  } catch (e) {
    view.innerHTML = html`<div class="note bad">${e.message || String(e)}</div>`;
  }
  view.focus({ preventScroll: true });
}

async function afterSignin() {
  await refreshWho();
  location.hash = "#/";
  route();
}

const WAIT_TEXT = {
  rate_limit: "Paused: the AI provider's rate limit. Trying again shortly.",
  retry: "The AI provider hiccupped. Trying again shortly.",
  budget: "Paused: this month's budget is used up.",
  auth: "Paused: the AI provider refused the API key.",
  quota: "Paused: the AI provider's credit is used up.",
};

async function status() {
  if (who.user && !who.user.must_change) {
    try {
      const s = await api("/api/status");
      const box = $("#activity");
      const waits = s.waiting.filter((w) => w.n > 0);
      let text = "";
      let warn = false;
      if (waits.length) {
        const w = waits.find((x) => x.wait_reason === "budget" || x.wait_reason === "auth" || x.wait_reason === "quota") || waits[0];
        text = html`${raw(icon("circle-alert", 15))}<span class="act-text">${WAIT_TEXT[w.wait_reason] || "Paused."}</span><span class="act-short">paused</span>`;
        if (can("admin")) text += ` <a href="#/settings">Settings</a>`;
        warn = true;
      } else if (s.busy) {
        text = `<span class="spinner"></span><span class="act-text">Working (${s.busy} to go)</span><span class="act-short">${s.busy}</span>`;
      } else if (s.checking_links) {
        text = `<span class="spinner"></span><span class="act-text">Checking reading links</span>`;
      }
      box.hidden = !text;
      box.classList.toggle("warn", warn);
      box.innerHTML = text;
      $("#banner").innerHTML = s.key_set ? "" : can("admin")
        ? html`<div class="note warn">Add an AI key in <a href="#/settings">Settings</a> to start making courses.</div>`
        : html`<div class="note warn">No AI key is set up yet. Ask an admin to add one.</div>`;
    } catch { /* signed out, or the server is restarting */ }
  } else {
    $("#activity").hidden = true;
    $("#banner").innerHTML = "";
  }
  setTimeout(status, 4000);
}

// light, dark or the device's choice, for everyone (saved on this device)
const THEMES = ["system", "light", "dark"];
function themeButton() {
  let pick = "system";
  try { pick = localStorage.getItem("knwlge-theme") || "system"; } catch { /* private mode */ }
  const b = $("#themebtn");
  const [ic, label] = { system: ["sun-moon", "auto"], light: ["sun", "light"], dark: ["moon", "dark"] }[pick];
  b.innerHTML = `${icon(ic, 15)}<span>${label}</span>`;
  b.title = `Theme: ${label} (click to change)`;
  b.onclick = () => {
    const next = THEMES[(THEMES.indexOf(pick) + 1) % THEMES.length];
    try { localStorage.setItem("knwlge-theme", next); } catch { /* private mode */ }
    if (next === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    const dark = next === "dark" || (next === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#161615" : "#efefe4");
    themeButton();
  };
}
themeButton();

// phones: the links, who's signed in and sign-out fold into a menu under the bar
function menuButton() {
  const b = $("#menubtn");
  const top = $(".top");
  const set = (open) => {
    top.classList.toggle("open", open);
    b.setAttribute("aria-expanded", String(open));
    b.innerHTML = icon(open ? "x" : "menu", 20);
    b.setAttribute("aria-label", open ? "Close the menu" : "Menu");
  };
  set(false);
  b.addEventListener("click", () => set(!top.classList.contains("open")));
  $("#topmenu").addEventListener("click", (e) => { if (e.target.closest("a, button")) set(false); });
  document.addEventListener("pointerdown", (e) => { if (top.classList.contains("open") && !e.target.closest(".top")) set(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && top.classList.contains("open")) { set(false); b.focus(); } });
  window.addEventListener("hashchange", () => set(false));
}
paintIcons();
menuButton();
document.addEventListener("knwlge:who", () => refreshWho());

// installable app: the service worker caches the app's own files (never courses or answers). Needs HTTPS or localhost.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* fine: the app works without it */ });
}

// draw diagrams wherever lesson content appears (views, the tutor)
let pending = false;
new MutationObserver(() => {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; enhance(document.body); });
}).observe(document.body, { childList: true, subtree: true });

window.addEventListener("hashchange", async () => {
  if ((location.hash === "#/signin" && who.user) || (location.hash !== "#/signin" && who.needs_signin && !who.user)) await refreshWho();
  route();
});

(async () => {
  try {
    await refreshWho();
  } catch (e) {
    view.innerHTML = html`<div class="note bad">Couldn't reach the server: ${e.message}</div>`;
    return;
  }
  route();
  status();
})();

export { esc, toast };
