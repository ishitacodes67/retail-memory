"""The 'dumb' router: before Groq tool-calling, a plain keyword-based dispatcher.
Exists to make the value of real tool-calling (Day 13+) visible by contrast, and
as a zero-dependency fallback that needs no API key or network access (NFR7).
"""

from __future__ import annotations

from enum import Enum


class Route(Enum):
    SALES_SUMMARY = "get_sales_summary"
    MARKDOWN = "recommend_markdown"
    UNKNOWN = "unknown"


def route(question: str) -> Route:
    q = question.lower()
    if any(w in q for w in ("summary", "sales", "revenue", "units sold", "how did")):
        return Route.SALES_SUMMARY
    if any(w in q for w in ("discount", "markdown", "price cut", "margin")):
        return Route.MARKDOWN
    return Route.UNKNOWN