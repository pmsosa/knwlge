# AI providers

See [index](index.md). Code: [app/providers.py](../../app/providers.py), used by [app/jobs.py](../../app/jobs.py).
Gemini's own client is [app/gemini.py](../../app/gemini.py) ([jobs-and-gemini](jobs-and-gemini.md)).

## One interface

Every job's request is built once, in Gemini's shape: a system prompt, text parts and inline files (`inlineData`),
a JSON Schema, and whether to search. `providers.generate(provider, model, ...)` translates it for the provider and
returns a `gemini.Result` (data, tokens, searches, sources, one entry per HTTP call for cost logging).
`providers.generate_image` does the same for illustrations. Every error is a `gemini.GeminiError` with the same kinds
(`rate_limit`, `quota`, `auth`, `server`, `network`, `bad_request`, `bad_output`, `blocked`), so the queue's
retries, pauses and failures work the same whichever provider answered.

| Kind | How | JSON output | Web search | Pictures | PDFs |
|---|---|---|---|---|---|
| `gemini` | `generateContent` over httpx (built in; key in `settings`) | `responseJsonSchema` | Google Search grounding | Nano Banana | inline |
| `openai` | Chat Completions over httpx; the Responses API when searching | `response_format: json_schema` (`text.format` when searching) | Responses `web_search` tool | `/images/generations` | `file` parts |
| `anthropic` | the official `anthropic` SDK, streamed | `output_config.format` | `web_search_20260209`, with `pause_turn` resumed | no | `document` blocks |
| `compatible` | Chat Completions over httpx at the given base URL | `json_schema`, falling back to `json_object` with the schema in the instructions | `web_search_options`, only when the admin ticks it (LiteLLM) | no | left out with a note |

Notes:

- **Claude**: no `temperature` (API version 2026-10-21 refuses it). For the newest models (`claude-fable-5-2`,
  `claude-fable-5-1`, `claude-opus-5-5`, `claude-opus-5`, `claude-sonnet-5-5`) requests go through the beta endpoint
  with Anthropic's server-side refusal fallback (`fallbacks: "default"`): a request a model declines is re-run on
  another Claude model inside the same call. A `refusal` that survives is `blocked`. When search and a schema can't be
  combined, it searches in plain text first and structures the notes in a second call.
- **OpenAI search**: Chat Completions only searches with OpenAI's `*-search-api` models, so a step that searches goes to
  `/responses` with `tools: [{"type": "web_search"}]` and the schema in `text.format`. Each `web_search_call` output
  item counts as one search; sources come from `url_citation` annotations and the call's `action.sources`. If the model
  won't combine search with JSON (a 400, or JSON that doesn't parse), it searches in plain text and Chat Completions
  shapes the notes, like Claude.
- **OpenAI-compatible search**: `providers.search` (a per-endpoint switch, off by default, because a server that ignores
  the field would otherwise claim research it never did) sends `web_search_options: {"search_context_size": "medium"}`.
  LiteLLM maps it to each provider's own search; searches are read from `usage.prompt_tokens_details.web_search_requests`
  and sources from `message.annotations`. A 400 with it retries without and says so.
- **Search where there is none**: a step that asked for search runs without it and says why (`search_note`), like a
  free-tier Gemini key. Reading suggestions are checked link by link anyway ([reading](reading.md)).
- **Keys** are stored in the database (the `providers` table, or the `gemini_api_key` setting), never returned by the
  API (only the last four characters), never logged, and never written to the audit log.

## Roles and routes

Jobs carry an old tier (`pro`, `flash`, `lite`, `image`) in their request. `providers.role_of(kind, tier)` maps a job
to one of seven roles:

| Role | Jobs |
|---|---|
| `planning` | `questions`, `plan`, sessions written with the `pro` tier (checkpoints, projects) |
| `writing` | other sessions, `revise` (section rewrites) |
| `checks` | `check`, marking short answers (`mark` with `lite`) |
| `marking` | marking written work (`mark` with `flash`) |
| `tutor` | `chat` |
| `research` | `reading` |
| `illustrations` | `illustration` (Gemini or OpenAI only) |

`route_<role>` in `settings` holds `{"provider", "model"}`. Without one (or if its provider was removed) the role uses
Gemini with the model its tier had (`model_<tier>` or the default), so an upgraded install behaves exactly as before.

## Testing and models

Adding a provider (`POST /api/providers`) tests it at once: list its models (`/models`, Gemini's model list,
or the SDK's `models.list()`), then ask one of them (or a chosen one) for a tiny JSON answer. The list and the
outcome are saved on the provider and shown in Settings. Admins can type prices per model (dollars per million input
and output tokens); `pricing.token_cost` uses them before the built-in tables (Gemini's dated prices, and Claude's).
Claude and OpenAI web searches add $10 per 1,000; an OpenAI-compatible endpoint's are what the admin typed per 1,000
(`providers.search_price`, free if blank). Gemini's searches count against Google's free 5,000 a month first.

## Tests

`tests/test_v03.py` fakes an OpenAI-style server with an `httpx.MockTransport` (`providers.transport`) and the
Anthropic SDK call with `providers.anthropic_call`, then builds whole courses with roles split across providers,
and checks errors pause work, the JSON fallback, refusals, prices and that keys never reach the browser.
