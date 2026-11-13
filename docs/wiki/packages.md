# Course packages and printing

See [index](index.md). Code: [app/package.py](../../app/package.py); the print view is
[app/static/js/views/print.js](../../app/static/js/views/print.js).

## The `.knwlge` format

A zip with:

| File | Holds |
|---|---|
| `manifest.json` | `format: "knwlge-course"`, `version: 1`, export time, title, session count, whether progress is in it |
| `course.json` | `course` (subject, notes, depth, title, summary, plan, questions and answers before planning, options, tags), `sessions`, `items` (with answer keys and rubrics), `media`, `reading` (verified only), `achievements` (themed) |
| `media/<key>.<ext>` | Files of ready media: pictures, recordings, video thumbnails, SVG drawings, experiments |
| `progress.json` | Only with `?progress=1`: the exporter's session progress and notes, marked attempts (no uploaded files), reveals and review queue |

Ids are stored relative to the course (`s01`, `s01-i02`, `s01-m11`), so an import gets fresh ones under a new course
id. Export is for a course's editors (`GET /api/courses/{id}/package`), and needs a written course.

## Import

`POST /api/import` (authors and admins) treats the package as untrusted:

- limits on the upload (200 MB), what's inside (400 MB unpacked, 3,000 entries, 30 MB of JSON), sessions, items,
  media and reading rows;
- files are only ever read by names this module builds from checked keys (`media/s01-m11.svg`), so a path in the
  package is never followed, and nothing is unpacked to disk as it is;
- every field is typed, clipped and checked against the app's own lists (kinds, sections, question types, rules);
  lesson content keeps only the keys the app uses;
- media goes through the same checks as new lessons (`media.check_item`, widget specs, experiment and SVG size
  rules); picture and audio files must really start like the format they claim, or they're dropped and fetched
  again from their description; an illustration or drawing with no usable file is left out (nothing is redrawn,
  since that costs money);
- reading suggestions come in as `pending` and are checked again before anyone sees them; only http(s) links;
- the course belongs to the importer, is a draft in team mode, lands on their shelf, and nothing is sent to an AI.

A session the package didn't have arrives as `failed`; **Try again** (`pipeline.retry`) queues it for writing.

## Printing

`GET /api/courses/{id}/print` returns every ready session with its content, questions and media in one response.
Answers (`?answers=1`) are included for the course's editors, and for others only on questions they've tried or
revealed. The `#/print/<id>` view lays it out as one long article; the `@media print` rules in `app.css` hide the app
around it, let the page grow past the app's fixed height, and start each session on a new page. Interactive media
(videos, recordings, widgets, experiments) become a one-line note.
