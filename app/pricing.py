"""Gemini prices in USD per 1M tokens, with the dates they take effect. From Google's published price list
(checked 2026-11-09). Prices drift: anything not listed is logged with an unknown cost, and the usage page says so."""
from __future__ import annotations

import datetime as dt

# model id -> list of (effective from, input $/1M, output $/1M), oldest first. Output includes thinking tokens.
PRICES: dict[str, list[tuple[dt.date, float, float]]] = {
    "gemini-4-argon": [(dt.date(2026, 1, 1), 2.00, 10.00), (dt.date(2026, 12, 1), 4.00, 20.00)],
    "gemini-3.1-pro-preview": [(dt.date(2026, 1, 1), 2.00, 12.00)],
    "gemini-3.8-flash": [(dt.date(2026, 1, 1), 0.75, 3.75), (dt.date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.6-flash": [(dt.date(2026, 1, 1), 0.75, 3.75)],
    "gemini-3.5-flash-lite": [(dt.date(2026, 1, 1), 0.30, 2.50)],
    "gemini-3.1-flash-lite": [(dt.date(2026, 1, 1), 0.25, 1.50)],
    # Nano Banana 2.1: output priced as image output ($30/1M); a default 1K picture is ~1,120 tokens, ~$0.034. No free tier.
    "gemini-nano-banana-2.1": [(dt.date(2026, 1, 1), 1.50, 30.00)],
}

# Claude prices (Anthropic's first-party API, as of 2026-11-03). Cache reads and writes are counted as input here.
CLAUDE_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-2": (8.00, 40.00), "claude-fable-5-1": (10.00, 50.00), "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00), "claude-opus-5": (5.00, 25.00), "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00), "claude-opus-4-6": (5.00, 25.00), "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00), "claude-sonnet-4-6": (3.00, 15.00), "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
}
CLAUDE_SEARCH_USD = 10.0 / 1000   # Anthropic's web search tool: $10 per 1,000 searches
OPENAI_SEARCH_USD = 10.0 / 1000   # OpenAI's web_search tool: $10 per 1,000 calls (search content tokens are in the usage)

# Grounding with Google Search on Gemini 3 and newer: billed per search query the model runs.
SEARCH_FREE_PER_MONTH = 5000
SEARCH_USD_PER_QUERY = 14.0 / 1000

DEFAULT_MODELS = {"pro": "gemini-4-argon", "flash": "gemini-3.8-flash", "lite": "gemini-3.5-flash-lite",
                  "image": "gemini-nano-banana-2.1"}

KNOWN_MODELS = [
    {"id": "gemini-4-argon", "label": "Gemini 4 Argon (top tier, no free tier)"},
    {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (preview)"},
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
    {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash (stable)"},
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite (stable)"},
    {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite (stable, cheapest)"},
    {"id": "gemini-nano-banana-2.1", "label": "Nano Banana 2.1 (pictures, ~3¢ each)"},
]


def rate(model: str, on: dt.date) -> tuple[float, float] | None:
    table = PRICES.get(model)
    if not table:
        return None
    current = None
    for start, inp, out in table:
        if on >= start:
            current = (inp, out)
    return current or (table[0][1], table[0][2])


def token_cost(model: str, input_tokens: int, output_tokens: int, on: dt.date,
               override: tuple[float, float] | None = None) -> float | None:
    """Cost in USD. `override` is an admin-entered price for the provider's model; otherwise the built-in tables."""
    r = override or rate(model, on) or CLAUDE_PRICES.get(model)
    if r is None:
        return None
    return input_tokens / 1e6 * r[0] + output_tokens / 1e6 * r[1]


def search_cost(queries: int, already_this_month: int) -> float:
    """Cost of `queries` more searches, given how many this app has already run this month."""
    free_left = max(0, SEARCH_FREE_PER_MONTH - already_this_month)
    return max(0, queries - free_left) * SEARCH_USD_PER_QUERY
