// Small helpers shared by every view.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

// Tagged template: values are escaped unless wrapped with raw(); arrays are joined.
export function html(strings, ...vals) {
  const one = (v) => (v && v.__raw !== undefined ? v.__raw : esc(v));
  return strings.reduce((out, s, i) => {
    if (i >= vals.length) return out + s;
    const v = vals[i];
    return out + s + (Array.isArray(v) ? v.map(one).join("") : one(v));
  }, "");
}
export const raw = (s) => ({ __raw: String(s ?? "") });

export function el(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstElementChild;
}

export class ApiError extends Error {}

// Who's using the app: { mode: "personal"|"team", needs_signin, setup_needed, user: {id, display_name, role, ...} }
export const who = { mode: "personal", needs_signin: false, setup_needed: false, user: null };
const RANK = { learner: 0, author: 1, admin: 2 };
export const can = (role) => !!who.user && RANK[who.user.role] >= RANK[role];
export const team = () => who.mode === "team";

export async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, headers: { "x-knwlge": "1" } };
  if (json !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  const r = await fetch(path, opts);
  const type = r.headers.get("content-type") || "";
  const body = type.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = (body && body.detail) || `Something went wrong (${r.status}).`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    // the server decides who's signed in: follow it to the sign-in or new-password screen
    const code = body && body.code;
    if (r.status === 401 && code === "signin" && !path.startsWith("/api/auth/")) {
      who.user = null;
      if (location.hash !== "#/signin") location.hash = "#/signin";
    } else if (r.status === 403 && code === "change_password" && location.hash !== "#/password") {
      location.hash = "#/password";
    }
    throw new ApiError(msg);
  }
  return body;
}

export function toast(msg, bad = false) {
  const box = document.getElementById("toast");
  const t = el(`<div class="t${bad ? " bad" : ""}">${esc(msg)}</div>`);
  box.append(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3000);
}

// Run an action from a button: disables it meanwhile and shows errors as a toast.
export async function act(button, fn) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (e) {
    toast(e.message || String(e), true);
    return undefined;
  } finally {
    if (button && button.isConnected) button.disabled = false;
  }
}

export const money = (v) => (v == null ? "—" : v > 0 && v < 0.01 ? "<$0.01" : `$${Number(v).toFixed(2)}`);
export const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export function ago(ts) {
  if (!ts) return "";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function hours(min) {
  if (min < 60) return `${min}\u00a0min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m ? `${h}\u00a0h ${m}\u00a0min` : `${h}\u00a0h`;
}

export const KIND_LABEL = { book: "Book", video: "Video", article: "Article", course: "Course", podcast: "Podcast", other: "Link", source: "Source" };

// Polling tied to the current view: a new view starts a new scope, which ends the old one's timers.
let pollToken = 0;
export function newPollScope() {
  pollToken += 1;
  const mine = pollToken;
  return {
    alive: () => mine === pollToken,
    every(ms, fn) {
      const tick = async () => {
        if (mine !== pollToken) return;
        let again = true;
        try { again = (await fn()) !== false; } catch { /* keep trying */ }
        if (again && mine === pollToken) setTimeout(tick, ms);
      };
      setTimeout(tick, ms);
    },
  };
}
