// Markdown + LaTeX -> safe HTML.
// Maths is cut out first (so Markdown can't mangle it) and replaced by private-use markers. The Markdown is rendered
// and sanitised; then markers are swapped for KaTeX output inside TEXT NODES only, never inside attributes.
/* global marked, DOMPurify, katex */

const OPEN = "";
const CLOSE = "";
const MARK = new RegExp(`${OPEN}(\\d+)${CLOSE}`);

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    const href = node.getAttribute("href");
    if (/^https?:\/\//i.test(href)) {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    } else if (!href.startsWith("#")) {
      node.removeAttribute("href");
    }
  }
});
export function md(text, { inline = false } = {}) {
  const maths = [];
  const stash = (tex, display) => {
    maths.push([tex.trim(), display]);
    return `${OPEN}${maths.length - 1}${CLOSE}`;
  };
  const parts = String(text ?? "").replace(/[]/g, "").split(/(```[\s\S]*?```|`[^`\n]*`)/g);
  const prepared = parts.map((p, i) => (i % 2 ? p : p
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => stash(t, true))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => stash(t, true))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => stash(t, false))
    .replace(/(^|[^\\$])\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\d)/g, (_, pre, t) => pre + stash(t, false))
  )).join("");
  const rendered = inline ? marked.parseInline(prepared, { gfm: true }) : marked.parse(prepared, { gfm: true, breaks: false });
  const frag = DOMPurify.sanitize(rendered, {
    RETURN_DOM_FRAGMENT: true,
    // external images could not load anyway (Content-Security-Policy)
    FORBID_TAGS: ["style", "form", "input", "iframe", "button", "textarea", "select", "img"],
  });
  const walker = document.createTreeWalker(frag, NodeFilter.SHOW_TEXT);
  const hits = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.includes(OPEN)) hits.push(walker.currentNode);
  for (const node of hits) {
    const bits = node.nodeValue.split(MARK);
    const out = document.createDocumentFragment();
    bits.forEach((b, i) => {
      if (i % 2 === 0) {
        if (b) out.append(b);
        return;
      }
      const [tex, display] = maths[Number(b)] || ["", false];
      const span = document.createElement("span");
      try {
        katex.render(tex, span, { displayMode: display, throwOnError: false, trust: false, output: "htmlAndMathml" });
      } catch {
        span.textContent = tex;
      }
      out.append(span);
    });
    node.replaceWith(out);
  }
  const box = document.createElement("div");
  box.append(frag);
  return box.innerHTML;
}
