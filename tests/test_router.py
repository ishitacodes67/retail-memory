"""Tests for the rule-based router -- including cases where keyword matching
visibly breaks, which is the point of building this version first."""

from retail_memory.agent.router import Route, route


def test_routes_sales_question():
    assert route("What were the sales for product X last month?") == Route.SALES_SUMMARY


def test_routes_markdown_question():
    assert route("Should I discount product X?") == Route.MARKDOWN


def test_unknown_for_unrelated_question():
    assert route("What's the weather today?") == Route.UNKNOWN


def test_fails_on_phrasing_without_keywords():
    # A real question a user would ask, with no routing keyword in it at all.
    # This SHOULD fail with the current router -- that's the point.
    assert route("Is product X doing well?") == Route.UNKNOWN


def test_fails_on_ambiguous_overlap():
    # Mentions both domains -- keyword matching can't disambiguate intent.
    result = route("How much revenue would a markdown on product X bring in?")
    assert result in (Route.SALES_SUMMARY, Route.MARKDOWN)  # whichever wins, document why