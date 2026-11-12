// Interactive exercises. A fixed set the app ships: Gemini only supplies the data (checked on the server too).
import { el, esc, html, raw } from "./util.js";
import { md } from "./md.js";

const shuffle = (a, seed = 1) => {
  const out = a.slice();
  let s = seed;
  for (let i = out.length - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor((s / 233280) * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
};
const inline = (t) => md(String(t ?? ""), { inline: true });
const norm = (s) => String(s).trim().toLowerCase().replace(/\s+/g, " ");

export function renderWidget(spec) {
  const make = { flashcards, order, match, cloze, timeline, plot }[spec.type];
  if (!make) return el(`<div class="widget faint small">Unknown exercise.</div>`);
  try { return make(spec); } catch (e) { return el(html`<div class="widget faint small">This exercise couldn't be shown (${e.message}).</div>`); }
}

function flashcards(spec) {
  const cards = spec.cards;
  let i = 0;
  let back = false;
  const box = el(html`<div class="widget"><div class="w-head">Flashcards · tap to flip</div>
    <div class="flash" tabindex="0" role="button"></div>
    <div class="row" style="margin-top:8px"><button class="ghost small" data-a="prev">← Back</button>
      <span class="small faint" data-count></span><button class="ghost small" data-a="next">Next →</button>
      <button class="link small" data-a="shuffle">Shuffle</button></div></div>`);
  const card = box.querySelector(".flash");
  const draw = () => {
    card.innerHTML = inline(back ? cards[i].back : cards[i].front);
    card.classList.toggle("back", back);
    box.querySelector("[data-count]").textContent = `${i + 1} / ${cards.length}`;
  };
  const flip = () => { back = !back; draw(); };
  card.addEventListener("click", flip);
  card.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); flip(); } });
  box.querySelector('[data-a="prev"]').addEventListener("click", () => { i = (i - 1 + cards.length) % cards.length; back = false; draw(); });
  box.querySelector('[data-a="next"]').addEventListener("click", () => { i = (i + 1) % cards.length; back = false; draw(); });
  box.querySelector('[data-a="shuffle"]').addEventListener("click", () => {
    cards.splice(0, cards.length, ...shuffle(cards, Date.now() % 1000)); i = 0; back = false; draw();
  });
  draw();
  return box;
}

function order(spec) {
  const correct = spec.items;
  let items = shuffle(correct, correct.length * 7 + 3);
  if (items.every((x, k) => x === correct[k])) items = items.slice().reverse();
  const box = el(html`<div class="widget"><div class="w-head">Put in order</div>
    ${raw(spec.prompt ? `<div class="small" style="margin-bottom:6px">${inline(spec.prompt)}</div>` : "")}
    <div class="w-list"></div><div class="row"><button class="small" data-a="check">Check order</button><span class="small" data-r></span></div></div>`);
  const list = box.querySelector(".w-list");
  const draw = (marks) => {
    list.innerHTML = items.map((t, k) => html`<div class="w-item ${marks ? (t === correct[k] ? "ok" : "no") : ""}">
      <span class="num">${k + 1}</span><span class="grow">${raw(inline(t))}</span>
      <button class="ghost" data-up="${k}" aria-label="Move up" ${raw(k === 0 ? "disabled" : "")}>↑</button>
      <button class="ghost" data-down="${k}" aria-label="Move down" ${raw(k === items.length - 1 ? "disabled" : "")}>↓</button></div>`).join("");
    list.querySelectorAll("[data-up]").forEach((b) => b.addEventListener("click", () => { const k = +b.dataset.up; [items[k - 1], items[k]] = [items[k], items[k - 1]]; draw(); }));
    list.querySelectorAll("[data-down]").forEach((b) => b.addEventListener("click", () => { const k = +b.dataset.down; [items[k + 1], items[k]] = [items[k], items[k + 1]]; draw(); }));
  };
  box.querySelector('[data-a="check"]').addEventListener("click", () => {
    draw(true);
    const right = items.filter((t, k) => t === correct[k]).length;
    box.querySelector("[data-r]").textContent = right === items.length ? "✓ All in the right order." : `${right} of ${items.length} in place. Move the orange ones.`;
  });
  draw();
  return box;
}

function match(spec) {
  const pairs = spec.pairs;
  const answers = shuffle(pairs.map((p) => p.right), pairs.length * 5 + 1);
  const box = el(html`<div class="widget"><div class="w-head">Match them up</div>
    ${raw(spec.prompt ? `<div class="small" style="margin-bottom:6px">${inline(spec.prompt)}</div>` : "")}
    <div class="w-match">${pairs.map((p, k) => raw(html`<div class="w-item" data-row="${k}"><span class="grow">${raw(inline(p.left))}</span></div>
      <select data-pick="${k}" aria-label="Match for item ${k + 1}"><option value="">Choose…</option>${answers.map((a) => raw(html`<option>${a}</option>`))}</select>`))}</div>
    <div class="row" style="margin-top:8px"><button class="small" data-a="check">Check</button><span class="small" data-r></span></div></div>`);
  box.querySelector('[data-a="check"]').addEventListener("click", () => {
    let right = 0;
    pairs.forEach((p, k) => {
      const ok = box.querySelector(`[data-pick="${k}"]`).value === p.right;
      right += ok;
      const row = box.querySelector(`[data-row="${k}"]`);
      row.classList.toggle("ok", ok);
      row.classList.toggle("no", !ok);
    });
    box.querySelector("[data-r]").textContent = right === pairs.length ? "✓ All matched." : `${right} of ${pairs.length} right.`;
  });
  return box;
}

function cloze(spec) {
  const answers = [];
  const text = String(spec.text).replace(/\{\{([^{}]+)\}\}/g, (_, a) => { answers.push(a.split("|").map(norm)); return `${answers.length - 1}`; });
  const box = el(html`<div class="widget"><div class="w-head">Fill the gaps</div><div class="prose cloze"></div>
    <div class="row" style="margin-top:8px"><button class="small" data-a="check">Check</button>
      <button class="ghost small" data-a="show">Show answers</button><span class="small" data-r></span></div></div>`);
  const holder = box.querySelector(".cloze");
  holder.innerHTML = md(text).replace(/(\d+)/g, (_, k) => `<input type="text" class="cloze-blank" data-blank="${k}" aria-label="Gap ${+k + 1}" autocomplete="off">`);
  const blanks = [...holder.querySelectorAll("[data-blank]")];
  box.querySelector('[data-a="check"]').addEventListener("click", () => {
    let right = 0;
    blanks.forEach((b) => {
      const ok = answers[+b.dataset.blank].includes(norm(b.value));
      right += ok;
      b.classList.toggle("ok", ok);
      b.classList.toggle("no", !ok);
    });
    box.querySelector("[data-r]").textContent = right === blanks.length ? "✓ All right." : `${right} of ${blanks.length} right.`;
  });
  box.querySelector('[data-a="show"]').addEventListener("click", () => blanks.forEach((b) => {
    if (!answers[+b.dataset.blank].includes(norm(b.value))) { b.value = answers[+b.dataset.blank][0]; b.classList.remove("no"); }
  }));
  return box;
}

function timeline(spec) {
  const box = el(html`<div class="widget"><div class="w-head">Timeline · tap an event</div>
    <div class="timeline">${spec.events.map((e, k) => raw(html`<div><button data-ev="${k}" aria-expanded="false"><b>${e.date}</b>${raw(inline(e.label))}</button>
      <div class="detail" hidden>${raw(inline(e.detail || ""))}</div></div>`))}</div></div>`);
  box.querySelectorAll("[data-ev]").forEach((b) => b.addEventListener("click", () => {
    const d = b.nextElementSibling;
    d.hidden = !d.hidden || !d.textContent.trim();
    b.setAttribute("aria-expanded", String(!d.hidden));
  }));
  return box;
}

// ---------- plot: a small, safe expression evaluator (no eval) ----------

const FUNCS = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan, sinh: Math.sinh,
  cosh: Math.cosh, tanh: Math.tanh, exp: Math.exp, log: Math.log, ln: Math.log, log10: Math.log10, log2: Math.log2,
  sqrt: Math.sqrt, abs: Math.abs, floor: Math.floor, ceil: Math.ceil, round: Math.round, sign: Math.sign,
  min: Math.min, max: Math.max, pow: Math.pow,
};

export function compile(src, names) {
  const toks = String(src).match(/\d*\.?\d+(?:e[+-]?\d+)?|[A-Za-z_][A-Za-z0-9_]*|[+\-*/^(),]|\S/gi) || [];
  let i = 0;
  const peek = () => toks[i];
  const take = (t) => { if (toks[i] !== t) throw new Error(`expected ${t}`); i++; };
  const expr = () => { let f = term(); while (peek() === "+" || peek() === "-") { const op = toks[i++]; const a = f, b = term(); f = op === "+" ? (v) => a(v) + b(v) : (v) => a(v) - b(v); } return f; };
  const term = () => { let f = power(); while (peek() === "*" || peek() === "/") { const op = toks[i++]; const a = f, b = power(); f = op === "*" ? (v) => a(v) * b(v) : (v) => a(v) / b(v); } return f; };
  const power = () => { const a = unary(); if (peek() === "^") { i++; const b = power(); return (v) => a(v) ** b(v); } return a; };
  const unary = () => { if (peek() === "-") { i++; const a = unary(); return (v) => -a(v); } if (peek() === "+") { i++; return unary(); } return primary(); };
  const primary = () => {
    const t = toks[i++];
    if (t === undefined) throw new Error("unexpected end");
    if (t === "(") { const f = expr(); take(")"); return f; }
    if (/^\d|^\./.test(t)) { const n = Number(t); return () => n; }
    if (t === "pi") return () => Math.PI;
    if (t === "e") return () => Math.E;
    if (Object.hasOwn(FUNCS, t)) {
      const fn = FUNCS[t];
      take("(");
      const args = [expr()];
      while (peek() === ",") { i++; args.push(expr()); }
      take(")");
      return (v) => fn(...args.map((a) => a(v)));
    }
    if (t === "x" || names.includes(t)) return (v) => v[t];
    throw new Error(`unknown name ${t}`);
  };
  const f = expr();
  if (i !== toks.length) throw new Error(`unexpected ${toks[i]}`);
  return f;
}

function plot(spec) {
  const params = spec.params || [];
  const f = compile(spec.expression, params.map((p) => p.name));
  const vals = Object.fromEntries(params.map((p) => [p.name, Number(p.value ?? p.min)]));
  const box = el(html`<div class="widget plot"><div class="w-head">Plot · y = ${spec.expression}</div><canvas></canvas>
    <div class="sliders">${params.map((p) => raw(html`<label><span>${p.name}</span><input type="range" min="${p.min}" max="${p.max}"
      step="${p.step || (p.max - p.min) / 100}" value="${vals[p.name]}" data-p="${p.name}"><output>${vals[p.name]}</output></label>`))}</div></div>`);
  const canvas = box.querySelector("canvas");
  const x0 = Number(spec.x_min ?? -10), x1 = Number(spec.x_max ?? 10);
  const draw = () => {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 300;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const g = canvas.getContext("2d");
    g.scale(dpr, dpr);
    const xs = [], ys = [];
    for (let k = 0; k <= 400; k++) {
      const x = x0 + ((x1 - x0) * k) / 400;
      const y = f({ ...vals, x });
      xs.push(x); ys.push(Number.isFinite(y) ? y : NaN);
    }
    const fin = ys.filter(Number.isFinite);
    let y0 = spec.y_min ?? Math.min(...fin, 0), y1 = spec.y_max ?? Math.max(...fin, 0);
    if (!(y1 > y0)) { y0 -= 1; y1 += 1; }
    const px = (x) => ((x - x0) / (x1 - x0)) * w, py = (y) => h - ((y - y0) / (y1 - y0)) * h;
    g.fillStyle = "#fcfcf9"; g.fillRect(0, 0, w, h);
    g.strokeStyle = "#d7d7d6"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, py(0)); g.lineTo(w, py(0)); g.moveTo(px(0), 0); g.lineTo(px(0), h); g.stroke();
    g.fillStyle = "#909090"; g.font = "11px 'IBM Plex Mono', monospace";
    g.fillText(String(x0), 4, py(0) - 4); g.fillText(String(x1), w - 30, py(0) - 4); g.fillText(String(+y1.toFixed(2)), px(0) + 4, 12);
    g.strokeStyle = "#5d8cd7"; g.lineWidth = 2.5; g.beginPath();
    let pen = false;
    xs.forEach((x, k) => { const y = ys[k]; if (!Number.isFinite(y)) { pen = false; return; } if (pen) g.lineTo(px(x), py(y)); else { g.moveTo(px(x), py(y)); pen = true; } });
    g.stroke();
  };
  box.querySelectorAll("[data-p]").forEach((r) => r.addEventListener("input", () => {
    vals[r.dataset.p] = Number(r.value);
    r.nextElementSibling.textContent = r.value;
    draw();
  }));
  requestAnimationFrame(draw);
  new ResizeObserver(() => draw()).observe(canvas);
  return box;
}

export { esc };
