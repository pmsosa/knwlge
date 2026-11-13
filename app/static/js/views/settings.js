import { $, $$, act, api, ago, html, raw, toast } from "../util.js";
import { icon } from "../icons.js";

export default async function settings(view) {
  const s = await api("/api/settings");
  let theme = "system";
  try { theme = localStorage.getItem("knwlge-theme") || "system"; } catch { /* private mode */ }
  const byId = Object.fromEntries(s.providers.map((p) => [p.id, p]));

  const providerCard = (p) => html`<div class="prov" data-pid="${p.id}">
    <div class="spread"><div><b>${p.label}</b> <span class="small faint">${[p.label === p.kind_label ? "" : p.kind_label, p.base_url].filter(Boolean).join(" · ")}</span></div>
      <span class="row" style="gap:4px">${raw(["search", "images", "pdf"].filter((k) => p.can[k]).map((k) =>
        `<span class="pill">${{ search: "web search", images: "pictures", pdf: "PDFs" }[k]}</span>`).join(""))}</span></div>
    <div class="small muted">${p.key_hint ? `Key ends ${p.key_hint}` : p.kind === "compatible" ? "No key (fine for a local server)" : "No key yet"}
      · ${p.models.length} model${p.models.length === 1 ? "" : "s"} listed${p.tested_at ? ` · tested ${ago(p.tested_at)}` : ""}</div>
    ${raw(p.test_note ? html`<div class="small" style="color:${/^Works/.test(p.test_note) ? "var(--ink)" : "var(--bad)"}">${p.test_note}</div>` : "")}
    <div class="row" style="margin-top:8px">
      <input type="password" class="pkey" autocomplete="off" placeholder="${p.key_hint ? "Paste a new key to replace it" : "Paste the API key"}" style="max-width:20rem">
      ${raw(p.builtin ? "" : html`<input type="text" class="purl" value="${p.base_url}" placeholder="Address" style="max-width:18rem" ${raw(p.kind === "compatible" || p.kind === "openai" ? "" : "hidden")}>`)}
      <button class="ghost small" data-pact="save">${raw(icon("check", 14))}Save</button>
      <button class="ghost small" data-pact="test">${raw(icon("refresh-cw", 14))}Test and list models</button>
      ${raw(p.builtin ? (p.key_hint ? `<button class="link small" data-pact="clearkey">Remove key</button>` : "") : `<button class="link small" data-pact="remove">Remove</button>`)}
    </div>
    ${raw(p.kind === "openai" || p.kind === "compatible" ? html`<div class="row search-opt" style="margin-top:8px">
      ${raw(p.kind === "compatible" ? html`<label class="row small" style="gap:6px"><input type="checkbox" data-psearch ${raw(p.can.search ? "checked" : "")}>
        Can search the web (LiteLLM's <code>web_search_options</code>)</label>` : `<span class="small muted">Web search through the Responses API.</span>`)}
      <label class="row small" style="gap:6px">$ <input type="number" min="0" step="0.5" data-psprice value="${p.search_price ?? ""}"
        placeholder="${p.kind === "openai" ? "10" : "0"}" style="width:5.5rem"> per 1,000 searches</label>
      <button class="ghost small" data-pact="search">Save search</button></div>` : "")}
    <details class="prices"><summary class="small muted">Prices (for Usage)</summary>
      <p class="small faint">Dollars per million tokens. Knwlge knows Gemini's and Claude's prices; add others here (0 for a free local model).
        Calls to models without a price are counted as unknown.</p>
      <div class="price-rows">${raw(p.models.slice(0, 40).map((m) => html`<label class="price-row"><span class="small">${m.id}</span>
        <input type="number" min="0" step="0.01" data-in="${m.id}" value="${m.price ? m.price[0] : ""}" placeholder="in">
        <input type="number" min="0" step="0.01" data-out="${m.id}" value="${m.price ? m.price[1] : ""}" placeholder="out"></label>`).join("")
        || `<span class="small faint">Test it first to list its models.</span>`)}</div>
      ${raw(p.models.length ? `<button class="ghost small" data-pact="prices">Save prices</button>` : "")}
    </details>
  </div>`;

  const routeRow = ([role, r]) => {
    const choices = s.providers.filter((p) => !r.needs_images || p.can.images);
    const p = byId[r.provider];
    const listed = (p ? p.models : []).map((m) => m.id);
    const custom = !listed.includes(r.model);
    return html`<div class="route" data-role="${role}"><label class="field">${r.title}</label><div class="field-hint">${r.hint}</div>
      <div class="row"><select class="rprov" aria-label="${`Provider for ${r.title}`}">${choices.map((x) => raw(html`<option value="${x.id}" ${raw(x.id === r.provider ? "selected" : "")}>${x.label}</option>`))}</select>
        <select class="rmodel" aria-label="${`Model for ${r.title}`}">${listed.map((m) => raw(html`<option value="${m}" ${raw(m === r.model ? "selected" : "")}>${m}</option>`))}
          <option value="__custom" ${raw(custom ? "selected" : "")}>Another model id…</option></select>
        <input type="text" class="rcustom" value="${custom ? r.model : ""}" placeholder="model id" style="max-width:16rem" ${raw(custom ? "" : "hidden")}></div></div>`;
  };

  view.innerHTML = html`<h1>Settings</h1>
    <div class="panel">
      <h2>Appearance</h2>
      <p class="muted small">Black on white, or white on black. "System" follows this device's light or dark setting. Saved on this device only.</p>
      <div class="row" role="radiogroup" aria-label="Theme">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) =>
        raw(html`<button class="small ${k === theme ? "" : "ghost"}" data-theme-pick="${k}" aria-pressed="${k === theme}">${l}</button>`))}</div>
    </div>
    <div class="panel stack">
      <div><h2>AI providers</h2>
        <p class="muted small">Keys are stored in Knwlge's database on this box and never sent to browsers. Gemini is built in;
          add OpenAI, Anthropic or any OpenAI-compatible endpoint (LiteLLM, Ollama, vLLM, LM Studio) to use them for some roles.</p></div>
      <div class="stack" id="provs">${raw(s.providers.map(providerCard).join(""))}</div>
      <details id="addprov"><summary><b>${raw(icon("plus", 14))} Add a provider</b></summary>
        <div class="stack" style="margin-top:10px">
          <div class="row"><select id="nkind" aria-label="Kind of provider">${Object.entries(s.kinds).map(([k, v]) => raw(html`<option value="${k}">${v.label}</option>`))}</select>
            <input type="text" id="nlabel" placeholder="Name (optional)" style="max-width:14rem"></div>
          <div class="row"><input type="text" id="nurl" placeholder="Address" style="max-width:24rem">
            <input type="password" id="nkey" autocomplete="off" placeholder="API key" style="max-width:20rem"></div>
          <label class="row small" id="nsearchrow" style="gap:6px"><input type="checkbox" id="nsearch">
            It can search the web (LiteLLM with <code>web_search_options</code>, for models that support it)</label>
          <p class="small faint" id="nhint" style="margin:0"></p>
          <div><button id="addgo">${raw(icon("plug", 15))}Add and test</button></div>
        </div></details>
    </div>
    <div class="panel stack">
      <div><h2>Who does what</h2><p class="muted small">Pick a provider and model for each kind of work. If one provider is over-cautious
        with a subject (medicine, chemistry, the history of warfare...), switch that role to another. Changes apply to new work.</p></div>
      ${raw(Object.entries(s.routes).map(routeRow).join(""))}
      <div><button class="ghost" id="saveroutes">${raw(icon("check", 15))}Save choices</button></div>
    </div>
    <div class="panel stack">
      <div><h2>Monthly budget</h2>
        <p class="muted small">Optional. When this month's estimated AI spend reaches it, new work pauses until next month (or until you raise it).
          Work already running finishes, so it can go slightly over.</p>
        <div class="row"><span>$</span><input type="number" id="budget" min="0" step="1" value="${s.budget_monthly_usd ?? ""}" placeholder="No limit" style="max-width:9rem">
          <button class="ghost" id="savebudget">Save budget</button>
          ${raw(s.budget_monthly_usd ? `<button class="link small" id="clearbudget">No limit</button>` : "")}</div></div>
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
      <p class="muted small">Work pauses when a provider rate-limits, refuses its key, or the budget is reached. Saving settings resumes it; so does this.</p>
      <button class="ghost" id="resume">${raw(icon("play", 15))}Resume paused work now</button>
    </div>`;

  // ----- adding a provider -----
  const hint = () => {
    const k = $("#nkind", view).value;
    const meta = s.kinds[k];
    $("#nurl", view).hidden = k === "anthropic";
    $("#nsearchrow", view).hidden = k !== "compatible";
    $("#nurl", view).value = k === "compatible" ? "" : meta.base_url;
    $("#nurl", view).placeholder = k === "compatible" ? "e.g. http://192.168.1.10:11434/v1 or http://litellm:4000/v1" : "Address";
    $("#nkey", view).placeholder = meta.needs_key ? "API key" : "API key (if the server wants one)";
    $("#nhint", view).textContent = {
      openai: "Chat Completions for writing, the Responses API with web search for live research and reading lists ($10 per 1,000 searches). Pictures with an image model such as gpt-image-1.",
      anthropic: "Claude, through Anthropic's own SDK. Has web search for live research and reading lists; can't draw pictures.",
      compatible: "Anything that speaks the OpenAI API. Local models work, but small ones can struggle to write a whole lesson as JSON; try one role first. Tick search only if the endpoint really searches (a LiteLLM proxy whose models have it); otherwise those steps are written without it.",
    }[k] || "";
  };
  $("#nkind", view).addEventListener("change", hint);
  hint();
  $("#addgo", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const r = await api("/api/providers", { method: "POST", json: { kind: $("#nkind", view).value, label: $("#nlabel", view).value,
      base_url: $("#nurl", view).hidden ? "" : $("#nurl", view).value, api_key: $("#nkey", view).value,
      search: $("#nkind", view).value === "compatible" && $("#nsearch", view).checked } });
    toast(r.test.ok ? `Added. ${r.test.message}` : `Added, but the test failed: ${r.test.message}`, !r.test.ok);
    settings(view);
  }));

  // ----- each provider -----
  $$(".prov", view).forEach((box) => {
    const pid = box.dataset.pid;
    box.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pact]");
      if (!b) return;
      const what = b.dataset.pact;
      act(b, async () => {
        if (what === "save") {
          const key = $(".pkey", box).value.trim();
          const url = $(".purl", box);
          await api(`/api/providers/${pid}`, { method: "PUT", json: { api_key: key || null, base_url: url && !url.hidden ? url.value : null } });
          toast("Saved.");
          if (key) {
            const t = await api(`/api/providers/${pid}/test`, { method: "POST", json: {} });
            toast(t.ok ? t.message : `The test failed: ${t.message}`, !t.ok);
          }
        } else if (what === "test") {
          const t = await api(`/api/providers/${pid}/test`, { method: "POST", json: {} });
          toast(t.ok ? t.message : `The test failed: ${t.message}`, !t.ok);
        } else if (what === "clearkey") {
          if (!confirm("Remove the Gemini key? Roles that use Gemini pause until you add one.")) return;
          await api("/api/settings", { method: "PUT", json: { clear_key: true } });
        } else if (what === "remove") {
          if (!confirm("Remove this provider? Roles that used it go back to Gemini.")) return;
          await api(`/api/providers/${pid}`, { method: "DELETE" });
        } else if (what === "search") {
          const box2 = $("[data-psearch]", box), price = $("[data-psprice]", box).value;
          await api(`/api/providers/${pid}`, { method: "PUT", json: { search: box2 ? box2.checked : null,
            search_price: price === "" ? null : Number(price), clear_search_price: price === "" } });
          toast("Saved.");
        } else if (what === "prices") {
          const prices = {};
          $$("[data-in]", box).forEach((i) => {
            const o = box.querySelector(`[data-out="${CSS.escape(i.dataset.in)}"]`);
            prices[i.dataset.in] = i.value === "" && o.value === "" ? null : [Number(i.value || 0), Number(o.value || 0)];
          });
          await api(`/api/providers/${pid}`, { method: "PUT", json: { prices } });
          toast("Prices saved.");
        }
        settings(view);
      });
    });
  });

  // ----- roles -----
  $$(".route", view).forEach((row) => {
    const prov = $(".rprov", row), model = $(".rmodel", row), custom = $(".rcustom", row);
    prov.addEventListener("change", () => {
      const ids = (byId[prov.value]?.models || []).map((m) => m.id);
      model.innerHTML = ids.map((m) => html`<option value="${m}">${m}</option>`).join("") + `<option value="__custom">Another model id…</option>`;
      custom.hidden = ids.length > 0;
      if (!ids.length) model.value = "__custom";
    });
    model.addEventListener("change", () => { custom.hidden = model.value !== "__custom"; });
  });
  $("#saveroutes", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const body = {};
    $$(".route", view).forEach((row) => {
      const m = $(".rmodel", row).value;
      body[row.dataset.role] = { provider: $(".rprov", row).value, model: m === "__custom" ? $(".rcustom", row).value.trim() : m };
    });
    await api("/api/routes", { method: "PUT", json: body });
    toast("Saved. New work uses these.");
    settings(view);
  }));

  // ----- the rest, as before -----
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
  $("#resume", view).addEventListener("click", (e) => act(e.currentTarget, async () => {
    const r = await api("/api/jobs/resume", { method: "POST" });
    toast(r.resumed ? `Resumed ${r.resumed} paused step${r.resumed > 1 ? "s" : ""}.` : "Nothing was paused.");
  }));
}
