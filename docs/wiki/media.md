# Media

See [index](index.md). Code: [app/media.py](../../app/media.py), front end [app/static/js/media.js](../../app/static/js/media.js),
[app/static/js/widgets.js](../../app/static/js/widgets.js).

Gemini proposes media per lesson chunk (at most five per session, only the kinds the course's extras allow; the schema
itself is built from the options). The app checks every proposal and fetches what it can, so nothing loads from
outside while someone studies.

| Kind | Stored as | Shown as |
|---|---|---|
| `mermaid` | Source text | Drawn in the browser by Mermaid in strict mode |
| `svg` | A file, checked to be SVG | An `<img>`, so scripts inside can't run |
| `widget` | JSON data, validated server-side per widget type | Flashcards, order, match, fill-the-gaps, timeline, plot (a small expression parser, never `eval`) |
| `image`, `audio` | Searched on Wikimedia Commons (free licences only), downloaded, with author and licence | Served from Knwlge with a credit line |
| `video` | A YouTube id checked via oEmbed; the thumbnail is downloaded | The no-cookie player, loaded only on **play** |
| `illustration` | An `illustration` job with the image model (budgeted) | Labelled "AI illustration"; not used for real artworks or people |
| `experiment` | An HTML file | A sandboxed frame with its own strict CSP, started on **run experiment** ([security](security.md#experiments)) |

Fetching runs in the worker's idle time (`media.step`), one item at a time, with status `pending` → `working` →
`ready` / `failed`; the session page swaps items in as they finish. Media that couldn't be found are dropped quietly
and noted for editors.
