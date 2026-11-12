# Frontend

See [index](index.md). Code: [app/static/](../../app/static/). Plain HTML, CSS and ES modules; no build step, no CDN.

## Modules

| File | Does |
|---|---|
| [index.html](../../app/static/index.html) | The shell: top bar (nav, activity, who's signed in, theme button), `#view`, toasts |
| [js/main.js](../../app/static/js/main.js) | Hash router, route guard (sign-in, forced password change), role-aware nav, activity indicator, diagram observer |
| [js/util.js](../../app/static/js/util.js) | `html` tagged template (escapes by default, `raw()` to opt out), `api()` (adds `x-knwlge`, handles 401/403), `who`/`can`/`team`, toasts, poll scopes |
| [js/md.js](../../app/static/js/md.js) | Markdown with marked → DOMPurify, then KaTeX for maths placed into text nodes |
| [js/items.js](../../app/static/js/items.js) | Questions, exercises and projects: answering, feedback, reveals, editing |
| [js/media.js](../../app/static/js/media.js), [js/widgets.js](../../app/static/js/widgets.js) | Media cards, Mermaid, the sandboxed experiment frame; the interactive widgets |
| [js/tutor.js](../../app/static/js/tutor.js) | The tutor bubble and its chat window (`mountTutor`, `openChat`, `removeTutor`) |
| [js/sectionmenu.js](../../app/static/js/sectionmenu.js) | The right-click section menu and its Edit / Rewrite / Add dialogs |
| [js/theme.js](../../app/static/js/theme.js) | Applies the saved theme before first paint |
| [js/readingmode.js](../../app/static/js/readingmode.js) | The Reading mode switch (course sidebar and session toolbar) and the list of quiz-like widgets it hides |
| [sw.js](../../app/static/sw.js) | The service worker, served at `/sw.js` with its build stamp ([below](#installable-app)) |
| [js/icons.js](../../app/static/js/icons.js) | `icon(name, size)` returns inline SVG markup for a Lucide icon; `paintIcons()` fills `data-icon` elements in `index.html`; `KIND_ICON` for reading kinds |
| `js/views/*.js` | One per page: home, new, course, session, settings, usage, people, audit, signin |

## Patterns

- **Views** are `async function(view, scope, ...params)`; `scope` (a poll scope) runs `every(ms, fn)` loops that stop
  when the route changes. Pages poll while something is being made (course status, session writing, media, section
  rewrites, the tutor's answer) and redraw only what changed, keeping the pane's scroll position.
- **Layout:** an app shell. The top bar is fixed and only content scrolls; courses and sessions use a two-pane
  `.split` (outline left, `.pane` right). Lesson text is one centred column (up to 720 px) and justified with
  hyphenation on wide screens; left-aligned under 860 px.
- **Tutor bubble:** `mountTutor(course, scope, title)` on course and session pages (idempotent, so redraws keep an
  open chat). `openChat(...)` opens it about a question or a quoted passage. Removed on every route change.
- **Section menu:** `contextmenu` on `.chunk[data-chunk]` (not on questions, inputs or media; not with Shift; not
  after a touch long-press) opens `.ctx-menu`; editors also get a `⋯` button per heading. Dialogs are native
  `<dialog>` with `showModal()`. Keyboard: arrows move through the menu, Esc closes, Ctrl+Enter sends a rewrite.
- **Header:** on a desk the nav, who's signed in, the activity and the theme button sit in one row. Below 1100 px the
  `.topmenu` (nav and who's signed in) folds into a sheet opened by `#menubtn`; it closes on navigation, Esc or a tap
  outside. The activity shows just a spinner and a count there.
- **Icons:** Lucide, trimmed at build time to the names in `ICONS` in [tools/vendor.py](../../tools/vendor.py) and served
  as `/vendor/lucide/icons.js`. Add a name there before using it; [tests/test_icons.py](../../tests/test_icons.py) fails
  if the front end asks for one that isn't built in. Icons are decorative (`aria-hidden`); buttons keep their text or an
  `aria-label`.
- **Roles in the UI:** `data-min="author|admin"` and `data-team` on nav links; views check `can()` and the API's
  `can_edit`. The server enforces all of it regardless.

## Installable app

`/manifest.webmanifest` (name, colours, 192/512 and maskable icons) and a service worker at `/sw.js`, registered by
`main.js` in secure contexts (HTTPS or localhost). The server stamps the worker with a fingerprint of the front end's
files (`_build_version()` in [main.py](../../app/main.py)), so each build gets its own cache and the old one is deleted
on activation. The worker caches only the app's own files (`/static`, `/vendor`, the icons, the manifest) and keeps the
shell (`/`) for opening offline; page loads go to the network first. It never touches `/api`, so courses, answers and
accounts always come from the server.

## Look

The **Paper** style: cream canvas `#efefe4`, paper-white cards, near-black ink as the only action colour, two-tone
headlines, Studio Blue `#5d8cd7` for diagrams and code accents, a muted red only for errors. Buttons are lower-case.
Dark theme via `:root[data-theme="dark"]` (or the OS setting on auto). Fonts: Inter Tight, Inter, IBM Plex Mono.
Icons and logo from `docs/brand/logo-mark.png` (the green leaf K).

## Vendored libraries

[tools/vendor.py](../../tools/vendor.py) runs in the image's first build stage: it downloads marked, DOMPurify,
KaTeX, Mermaid, the fonts and the Lucide icons from npm, checks each tarball against its published sha512, and copies only the needed
files to `/srv/vendor` (served at `/vendor`).

## Testing it

The Python tests cover the API. [tests/e2e/smoke.py](../../tests/e2e/smoke.py) drives the real app in Chromium against a
team-mode demo: signing in, the nav per role, a course and a session, the section menu, the tutor, Reading mode on and
off, the service worker, the admin pages, a learner's view and the phone menu, and fails on any page error. Run it
with `sh tools/e2e.sh` ([operations](operations.md#browser-tests-and-screenshots)).
