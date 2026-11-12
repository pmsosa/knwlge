"""Browser smoke test: drives the real app (a team-mode demo, see tools/e2e.sh) in Chromium and checks the main paths.

    python tests/e2e/smoke.py http://localhost:9199

Needs Playwright for Python with Chromium. Exits non-zero on the first failed check, or if a page logged an error.
"""
import sys

from playwright.sync_api import Page, expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9199").rstrip("/")
PEOPLE = {"maya": "demo-maya-password", "sam": "demo-sam-password", "kim": "demo-kim-password"}   # app.demo --team
errors: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok:
        raise SystemExit(f"failed: {name}")


def watch(page: Page) -> Page:
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"{page.url}: {m.text}"))
    return page


def sign_in(page: Page, user: str) -> None:
    page.goto(f"{BASE}/#/signin")
    page.fill("#u", user)
    page.fill("#p", PEOPLE[user])
    page.keyboard.press("Enter")
    page.wait_for_selector(".top nav:not([hidden])")


def course_ids(page: Page) -> dict:
    return {c["title"]: c["id"] for c in page.evaluate("() => fetch('/api/courses').then(r => r.json())")}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---- an admin on a desk ----
        page = watch(browser.new_context(viewport={"width": 1440, "height": 900}).new_page())
        page.goto(BASE)
        page.wait_for_selector("#u")
        check("signed out: the sign-in page shows", page.locator("#u").is_visible())
        sign_in(page, "maya")
        check("admin: every nav link", page.locator(".top nav a:visible").count() == 6)
        check("courses page lists the demo courses", page.locator(".grid .card, .grid a").count() >= 3)
        ids = course_ids(page)
        music = next(v for k, v in ids.items() if "Music" in k)

        page.goto(f"{BASE}/#/course/{music}")
        page.wait_for_selector(".vtabs")
        check("course page: four tabs for an editor", page.locator(".vtabs [data-tab]").count() == 4)
        check("course page: the tutor bubble", page.locator(".tutor-fab").is_visible())

        page.goto(f"{BASE}/#/session/{music}-s01")
        page.wait_for_selector(".chunk .prose p")
        check("session: lesson parts", page.locator(".chunk").count() >= 2)
        check("session: questions", page.locator(".q").count() > 0)

        para = page.locator(".chunk[data-chunk='0'] .prose p").first
        para.click(button="right")
        page.wait_for_selector(".ctx-menu")
        check("right-click: the section menu with Edit", page.locator(".ctx-menu [data-do=edit]").count() == 1)
        page.keyboard.press("Escape")
        check("Esc closes the menu", page.locator(".ctx-menu").count() == 0)

        page.click(".tutor-fab")
        page.wait_for_selector(".tutor-panel textarea")
        check("tutor: the chat opens", page.locator(".tutor-panel").is_visible())
        page.click(".tutor-panel [data-act=close]")
        check("tutor: it closes", page.locator(".tutor-panel").count() == 0)

        page.click("#tools [data-reading-switch]")
        page.wait_for_selector("#tools .rm-switch.on")
        check("Reading mode: questions hidden", page.locator(".q").count() == 0)
        check("Reading mode: key points shown", page.get_by_text("Key points").count() >= 1)
        check("Reading mode: no practice heading", page.locator("h2.section-title", has_text="Practice").count() == 0)
        page.click("#tools [data-reading-switch]")
        page.wait_for_selector("#tools .rm-switch:not(.on)")
        check("Reading mode off: questions are back", page.locator(".q").count() > 0)

        reg = page.evaluate("() => navigator.serviceWorker ? navigator.serviceWorker.ready.then(r => !!r.active) : false")
        check("installable: the service worker is running", bool(reg))

        page.goto(f"{BASE}/#/account")
        page.fill("#dn", "Maya L. Lindqvist")
        page.click("#go")
        expect(page.locator(".who-name")).to_have_text("Maya L. Lindqvist")
        check("your name: renaming yourself updates the bar", True)
        page.fill("#dn", "Maya Lindqvist")
        page.click("#go")
        expect(page.locator(".who-name")).to_have_text("Maya Lindqvist")
        page.goto(f"{BASE}/#/course/{music}")
        page.wait_for_selector(".vtabs")
        check("no scores: no mastery on the course page", page.get_by_text("Mastery").count() == 0)

        for path, sel in (("#/people", "table"), ("#/audit", "#rows tr"), ("#/usage", "main h1, #view h1"), ("#/settings", "#view h1")):
            page.goto(f"{BASE}/{path}")
            page.wait_for_selector(sel)
        check("admin pages open", True)

        # ---- a learner ----
        learner = watch(browser.new_context(viewport={"width": 1280, "height": 900}).new_page())
        sign_in(learner, "kim")
        check("learner: no new-course link", learner.locator(".top nav a[href='#/new']:visible").count() == 0)
        learner.goto(f"{BASE}/#/session/{music}-s01")
        learner.wait_for_selector(".chunk .prose p")
        learner.locator(".chunk[data-chunk='0'] .prose p").first.click(button="right")
        learner.wait_for_selector(".ctx-menu")
        check("learner: the menu has no editing", learner.locator(".ctx-menu [data-do=edit]").count() == 0)
        learner.keyboard.press("Escape")

        # ---- a phone ----
        phone = watch(browser.new_context(**p.devices["Pixel 7"]).new_page())
        sign_in_phone = phone
        sign_in_phone.goto(f"{BASE}/#/signin")
        sign_in_phone.fill("#u", "maya")
        sign_in_phone.fill("#p", PEOPLE["maya"])
        sign_in_phone.keyboard.press("Enter")
        phone.wait_for_selector("#menubtn:not([hidden])")
        check("phone: links folded away", phone.locator(".top nav a[href='#/usage']").is_hidden())
        phone.click("#menubtn")
        expect(phone.locator(".top nav a[href='#/usage']")).to_be_visible()
        check("phone: the menu opens", True)
        phone.locator(".top nav a[href='#/usage']").click()
        phone.wait_for_timeout(400)
        check("phone: the menu closes after picking a page", not phone.evaluate("document.querySelector('.top').classList.contains('open')"))

        browser.close()
    if errors:
        print("\n".join(errors))
    check("no errors in any page", not errors)


if __name__ == "__main__":
    main()
