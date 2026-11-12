// Lucide icons (ISC), vendored at image build time by tools/vendor.py: only the ones listed there are available.
import ICONS from "/vendor/lucide/icons.js";

/** An inline SVG icon as markup (use inside html`` with raw()). Decorative: hidden from screen readers. */
export function icon(name, size = 16, cls = "") {
  const inner = ICONS[name];
  if (!inner) { console.warn("no icon", name); return ""; }
  return `<svg class="i${cls ? ` ${cls}` : ""}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" `
    + `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${inner}</svg>`;
}

/** Fill every element with data-icon="name" (static markup in index.html). */
export function paintIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.querySelector(":scope > svg.i")) return;
    el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon, Number(el.dataset.iconSize) || 16));
  });
}

/** Icons for reading-list kinds and course tabs, shared by the views. */
export const KIND_ICON = { book: "book", video: "video", article: "newspaper", course: "graduation-cap", podcast: "podcast",
  other: "link", source: "link" };
