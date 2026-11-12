// Media inside lessons. Everything is served by Knwlge itself except a YouTube player, which loads only when you
// press play, and experiments, which run in a sandboxed frame with no network.
import { el, html, raw } from "./util.js";
import { icon } from "./icons.js";
import { renderWidget } from "./widgets.js";

const WAITING = {
  image: "Finding a picture on Wikimedia Commons…",
  audio: "Finding a recording on Wikimedia Commons…",
  video: "Checking the video…",
  illustration: "Drawing an illustration…",
};

function caption(m, extra = "") {
  const credit = m.credit ? html`<span class="credit">${raw(m.source_url
    ? html`<a href="${m.source_url}" target="_blank" rel="noopener noreferrer">${m.credit}</a>` : html`${m.credit}`)}</span>` : "";
  return m.caption || credit || extra ? html`<figcaption>${raw(extra)}${m.caption}${raw(credit)}</figcaption>` : "";
}

export function renderMedia(m, { editing = false } = {}) {
  const fig = (inner, extra = "") => {
    const f = el(html`<figure class="media" data-media="${m.id}" data-status="${m.status}">${raw(inner)}${raw(caption(m, extra))}</figure>`);
    return f;
  };
  if (m.status === "failed") {
    return editing ? fig(html`<div class="waiting">Left out: ${m.error || "couldn't be found"}</div>`) : el(`<span data-media="${m.id}" hidden></span>`);
  }
  if (m.status !== "ready") return fig(html`<div class="waiting"><span class="spinner"></span>${WAITING[m.kind] || "Getting this ready…"}</div>`);
  const file = `/api/media/${encodeURIComponent(m.id)}/file`;
  switch (m.kind) {
    case "image":
      return fig(html`<div class="canvas"><a href="${file}" target="_blank" rel="noopener"><img src="${file}" alt="${m.caption}" loading="lazy"></a></div>`);
    case "illustration":
      return fig(html`<div class="canvas"><img src="${file}" alt="${m.caption}" loading="lazy"></div>`, `<span class="tag">AI illustration</span>`);
    case "svg":
      return fig(html`<div class="canvas"><img src="${file}" alt="${m.caption}" loading="lazy"></div>`);
    case "mermaid": {
      const f = fig(html`<div class="canvas"><div class="mermaid-src"></div><span class="waiting"><span class="spinner"></span>Drawing the diagram…</span></div>`);
      f.querySelector(".mermaid-src").textContent = m.spec.code;
      return f;
    }
    case "audio":
      return fig(html`<div class="audio"><audio controls preload="none" src="${file}"></audio></div>`, `<span class="tag">Listen</span>`);
    case "video": return videoFigure(m, fig);
    case "widget": {
      const f = fig("");
      f.prepend(renderWidget(m.spec));
      return f;
    }
    case "experiment": return experimentFigure(m, fig);
    default: return fig(`<div class="waiting">Unsupported media.</div>`);
  }
}

function videoFigure(m, fig) {
  const { id, start } = m.spec;
  const thumb = m.has_file ? html`<img src="/api/media/${m.id}/file" alt="">` : `<img alt="" style="background:#000">`;
  const f = fig(html`<button class="play" aria-label="Play the video (loads YouTube)">${raw(thumb)}<span>${raw(icon("play", 15))} Play · loads YouTube</span></button>`,
    `<span class="tag">Video</span>`);
  f.querySelector(".play").addEventListener("click", (e) => {
    const frame = el(html`<iframe class="frame" title="${m.caption || "Video"}"
      src="https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0&start=${start || 0}"
      allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen
      referrerpolicy="strict-origin-when-cross-origin"></iframe>`);
    e.currentTarget.replaceWith(frame);
  });
  return f;
}

function experimentFigure(m, fig) {
  const f = fig(html`<div class="runbar"><button class="small" data-run>${raw(icon("flask-conical", 15))}Run experiment</button>
    <span class="small">Runs in a locked-down frame with no network.</span></div>`, `<span class="tag">Experiment</span>`);
  f.querySelector("[data-run]").addEventListener("click", () => {
    const frame = el(html`<iframe class="lab" sandbox="allow-scripts" title="${m.caption || "Experiment"}"
      src="/api/media/${m.id}/experiment" referrerpolicy="no-referrer"></iframe>`);
    f.querySelector(".runbar").replaceWith(frame);
  });
  return f;
}

// ---------- Mermaid, loaded only when a page has a diagram ----------

let mermaidReady = null;
let seq = 0;

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/vendor/mermaid.js";
      s.onload = () => {
        // diagrams sit on a paper-white card in both themes, so the colours are fixed
        window.mermaid.initialize({
          startOnLoad: false, securityLevel: "strict", theme: "base", fontFamily: "Inter, sans-serif",
          flowchart: { htmlLabels: false }, // labels as SVG text, not HTML
          themeVariables: { background: "#fcfcf9", primaryColor: "#f3f3f4", primaryBorderColor: "#83837e", primaryTextColor: "#181818",
            lineColor: "#434341", secondaryColor: "#efefe4", tertiaryColor: "#fcfcf9", fontSize: "14px", noteBkgColor: "#fcfcf9",
            fontFamily: "Inter, sans-serif" },
        });
        resolve(window.mermaid);
      };
      s.onerror = () => reject(new Error("Couldn't load the diagram library."));
      document.head.append(s);
    });
  }
  return mermaidReady;
}

// Draws any pending diagrams inside `root`: media figures, and ```mermaid blocks written straight into lesson text.
export async function enhance(root) {
  const fromMedia = [...root.querySelectorAll(".mermaid-src:not([data-done])")];
  const fromText = [...root.querySelectorAll("pre > code.language-mermaid:not([data-done])")];
  if (!fromMedia.length && !fromText.length) return;
  const todo = [...fromMedia, ...fromText];
  todo.forEach((src) => { src.dataset.done = "1"; });   // claim them now, so a second call can't draw them again
  let mermaid;
  try { mermaid = await loadMermaid(); } catch { return; }
  for (const src of todo) {
    const code = src.textContent;
    const target = src.parentElement;
    try {
      const { svg } = await mermaid.render(`mmd-${++seq}`, code);
      const holder = document.createElement("div");
      holder.className = "mermaid-out";
      holder.innerHTML = svg;
      if (src.classList.contains("mermaid-src")) {
        target.querySelector(".waiting")?.remove();
        target.append(holder);
      } else {
        const wrap = el(`<figure class="media"><div class="canvas"></div></figure>`);
        wrap.firstElementChild.append(holder);
        target.replaceWith(wrap);
      }
    } catch {
      if (src.classList.contains("mermaid-src")) {
        target.querySelector(".waiting")?.remove();
        const pre = document.createElement("pre");
        pre.textContent = code;
        target.append(pre);
      }
      document.getElementById(`dmmd-${seq}`)?.remove(); // mermaid leaves an error node in <body>
    }
  }
}
