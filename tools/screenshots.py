"""Take the user guide's screenshots (wiki/images) from a team-mode demo. See tools/e2e.sh, which runs this.

    python tools/screenshots.py http://localhost:9199 /out

Needs Playwright for Python with Chromium, and Pillow to shrink the PNGs. Every name and course in them is made up.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
PW = {"maya": "demo-maya-password", "kim": "demo-kim-password"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 1440, "height": 1000}).new_page()

        def shot(name, wait=600):
            pg.wait_for_timeout(wait)
            pg.evaluate("() => { const t = document.getElementById('toast'); if (t) t.replaceChildren(); }")   # no leftover toasts
            pg.screenshot(path=str(OUT / f"{name}.png"))
            print("shot", name, flush=True)

        def go(h, sel=None):
            pg.goto(f"{BASE}/{h}")
            pg.wait_for_load_state("networkidle")
            if sel:
                pg.wait_for_selector(sel)

        def select_text(chunk, para=0, end=None):
            pg.evaluate("""([c, n, end]) => { const p = document.querySelectorAll(`.chunk[data-chunk='${c}'] .prose p`)[n];
              const r = document.createRange(); if (end) { r.setStart(p.firstChild, 0); r.setEnd(p.firstChild, end); }
              else r.selectNodeContents(p); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""", [chunk, para, end])

        go("#/signin", "#u")
        shot("signin")
        pg.fill("#u", "maya")
        pg.fill("#p", PW["maya"])
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".top nav:not([hidden])")
        ids = {c["title"]: c["id"] for c in pg.evaluate("() => fetch('/api/courses').then(r => r.json())")}
        music = next(v for k, v in ids.items() if "Music" in k)
        astro = next(v for k, v in ids.items() if "Astronomy" in k)
        jazz = next(v for k, v in ids.items() if "Jazz" in k)
        s1 = f"{music}-s01"

        go("#/", ".grid")
        shot("courses")
        go("#/new", "form")
        pg.fill("#subject", "How bread works: yeast, gluten and the oven")
        shot("new-course")
        go(f"#/course/{jazz}", "#view h1")
        shot("plan")
        go(f"#/course/{music}", ".vtabs")
        shot("course")
        go(f"#/course/{music}/reading", ".vtabs")
        shot("reading")
        go(f"#/course/{music}/manage", ".vtabs")
        shot("course-settings")
        go(f"#/course/{music}/achievements", ".achs .ach")
        shot("achievements")
        go(f"#/print/{music}", ".print-session")
        shot("print", 1200)
        go("#/import", "#pf")
        shot("import")
        go(f"#/course/{astro}", ".vtabs")
        shot("course-building")
        go(f"#/session/{s1}", ".chunk .prose p")
        shot("session", 1500)

        select_text(0, 0, 44)
        bb = pg.locator(".chunk[data-chunk='0'] .prose p").first.bounding_box()
        pg.mouse.click(bb["x"] + 80, bb["y"] + 8, button="right")
        pg.wait_for_selector(".ctx-menu")
        shot("section-menu", 300)
        pg.click(".ctx-menu [data-do=rewrite]")
        pg.fill("#rv-wish", "Use a playground swing as the analogy instead of a guitar string.")
        shot("rewrite-section", 300)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        pg.mouse.click(bb["x"] + 80, bb["y"] + 8, button="right")
        pg.wait_for_selector(".ctx-menu")
        pg.click(".ctx-menu [data-do=edit]")
        shot("edit-section", 400)
        pg.click("[data-view=preview]")
        shot("edit-preview", 400)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        select_text(0, 1)
        bb2 = pg.locator(".chunk[data-chunk='0'] .prose p").nth(1).bounding_box()
        pg.mouse.click(bb2["x"] + 80, bb2["y"] + 8, button="right")
        pg.click(".ctx-menu [data-do=ask]")
        pg.wait_for_selector(".tutor-panel")
        pg.fill(".tutor-input textarea", "Why do compressions and rarefactions alternate?")
        shot("tutor", 400)
        pg.click(".tutor-panel [data-act=close]")

        pg.locator(".plot").first.evaluate("e => e.scrollIntoView({block: 'start'})")
        pg.locator("#pane").evaluate("e => e.scrollBy(0, -90)")
        shot("interactive", 900)
        pg.locator("h2.section-title", has_text="Written exercise").first.evaluate("e => e.scrollIntoView({block: 'start'})")
        pg.locator("#pane").evaluate("e => e.scrollBy(0, -20)")
        shot("feedback", 600)
        pg.locator("h2.section-title", has_text="Practice").first.evaluate("e => e.scrollIntoView({block: 'start'})")
        shot("practice", 600)

        # Reading mode: the same session, just the reading (then back off, so the other shots keep their questions)
        pg.locator("#pane").evaluate("e => e.scrollTo(0, 0)")
        pg.click("#tools [data-reading-switch]")
        pg.wait_for_selector("#tools .rm-switch.on")
        pg.locator("#pane").evaluate("e => e.scrollTo(0, 0)")
        shot("reading-mode", 1200)
        pg.locator(".wrapup").first.evaluate("e => e.scrollIntoView({block: 'center'})")
        shot("reading-mode-wrapup", 600)
        pg.click("#tools [data-reading-switch]")
        pg.wait_for_selector("#tools .rm-switch:not(.on)")

        go("#/settings", ".prov")
        shot("settings")
        pg.locator(".route").first.evaluate("e => e.scrollIntoView({block: 'start'})")
        pg.evaluate("() => document.getElementById('view').scrollBy(0, -70)")
        shot("providers-roles", 400)
        go("#/dashboard", ".funnel")
        shot("dashboard", 800)
        go("#/usage", "#view h1")
        shot("usage")
        go("#/people", "table")
        shot("people")
        go("#/audit", "#rows tr")
        shot("audit")

        pg.evaluate("() => { localStorage.setItem('knwlge-theme', 'dark'); }")
        go(f"#/session/{s1}", ".chunk .prose p")
        pg.reload()   # the theme is applied as the page loads
        pg.wait_for_selector(".chunk .prose p")
        shot("dark", 1500)

        ph = br.new_context(**p.devices["Pixel 7"]).new_page()
        ph.goto(f"{BASE}/#/signin")
        ph.fill("#u", "kim")
        ph.fill("#p", PW["kim"])
        ph.keyboard.press("Enter")
        ph.wait_for_selector("#menubtn:not([hidden])")
        ph.goto(f"{BASE}/#/session/{s1}")
        ph.wait_for_selector(".chunk .prose p")
        ph.wait_for_timeout(1500)
        ph.screenshot(path=str(OUT / "phone.png"))
        ph.goto(f"{BASE}/#/")
        ph.wait_for_timeout(1200)
        ph.click("#menubtn")
        ph.wait_for_timeout(300)
        ph.screenshot(path=str(OUT / "phone-learner-home.png"))
        print("shot phone, phone-learner-home", flush=True)
        br.close()

    # shrink: these are flat UI pictures, so 256 colours without dithering look the same at a third of the size
    from PIL import Image
    for f in OUT.glob("*.png"):
        Image.open(f).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(f, optimize=True)


if __name__ == "__main__":
    main()
