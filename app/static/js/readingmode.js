// Reading mode: one person reads a course without its questions, practice, written work and warm-ups.
// Everything is still written and kept; switching it off brings it all back.
import { api, html, raw, toast } from "./util.js";
import { icon } from "./icons.js";

/** Markup for the switch. Wire it with wireReadingSwitch() on a container (delegated, so redraws keep working). */
export function readingSwitch(on, { compact = false } = {}) {
  return html`<button type="button" class="rm-switch ${on ? "on" : ""}" role="switch" aria-checked="${on}" data-reading-switch
    title="${on ? "Reading mode is on: questions and exercises are hidden for you" : "Hide questions and exercises: just read"}">
    ${raw(icon("book-open", 15))}<span>Reading mode</span><span class="rm-track" aria-hidden="true"><span></span></span>
  </button>${raw(compact ? "" : html`<div class="small faint rm-hint">${on
    ? "Questions, practice and written work are hidden for you. Nothing is deleted."
    : "Just want to read? Hide the questions and exercises, for you only."}</div>`)}`;
}

/** Clicking any switch inside `root` turns Reading mode on or off for this course, then calls `done(on)`. */
export function wireReadingSwitch(root, courseId, done) {
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-reading-switch]");
    if (!b || b.disabled) return;
    const on = b.getAttribute("aria-checked") !== "true";
    b.disabled = true;
    try {
      await api(`/api/courses/${courseId}/reading`, { method: "PUT", json: { on } });
      toast(on ? "Reading mode on: just the reading." : "Reading mode off: questions and exercises are back.");
      await done(on);
    } catch (err) {
      toast(err.message || String(err), true);
    } finally {
      b.disabled = false;
    }
  });
}

/** Widgets that are really exercises in disguise; Reading mode hides them. Plots and timelines stay. */
export const QUIZ_WIDGETS = new Set(["flashcards", "order", "match", "cloze"]);
