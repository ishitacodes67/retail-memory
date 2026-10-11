"""Tests for agent guardrails -- retry, max-turns, and failure handling.
Mocks the Groq client so these run without a real API key or network (NFR7)."""

from unittest.mock import MagicMock

import duckdb
import groq
import httpx
import pytest

from retail_memory.agent.loop import (
    MAX_RETRY_ATTEMPTS,
    _call_with_retry,
    answer_question,
)


def _rate_limit_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
    return groq.RateLimitError("rate limited", response=response, body=None)


def fake_tool_call(name: str, args: str) -> MagicMock:
    call = MagicMock()
    call.id = f"call_{name}"
    call.function.name = name
    call.function.arguments = args
    return call


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < MAX_RETRY_ATTEMPTS:
            raise _rate_limit_error()
        return "ok"

    assert _call_with_retry(flaky) == "ok"
    assert calls["n"] == MAX_RETRY_ATTEMPTS


def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise _rate_limit_error()

    with pytest.raises(groq.RateLimitError):
        _call_with_retry(always_fails)
    assert calls["n"] == MAX_RETRY_ATTEMPTS


def test_max_turns_guard_fires_on_multiple_tool_calls():
    """If the API returns >MAX_TOOL_CALLS_PER_QUESTION calls, the guard must
    fire and refuse -- must not silently process only tool_calls[0].
    This protects the guard against a future refactor moving the check after
    `call = msg.tool_calls[0]`.
    """
    fake_response = MagicMock()
    fake_response.choices[0].message.tool_calls = [
        fake_tool_call("get_sales_summary", '{"product_id":1,"start_week":1,"end_week":2}'),
        fake_tool_call("recommend_markdown", '{"product_id":1,"margin":0.3}'),
    ]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    con = duckdb.connect()  # no tables needed, guard fires before any tool runs
    try:
        result = answer_question(con, fake_client, "irrelevant -- response is mocked")
    finally:
        con.close()

    assert result.status != "answered"
    assert result.tool_called is None
    assert "tool calls" in result.final_text.lower()