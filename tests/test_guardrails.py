"""Tests for agent guardrails -- retry, max-turns, and failure handling.
Mocks the Groq client so these run without a real API key or network (NFR7)."""

import groq
import httpx
import pytest

from retail_memory.agent.loop import MAX_RETRY_ATTEMPTS, _call_with_retry


def _rate_limit_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
    return groq.RateLimitError("rate limited", response=response, body=None)


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