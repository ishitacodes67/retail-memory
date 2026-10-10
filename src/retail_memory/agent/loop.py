"""The real agent loop: route -> validate params -> execute -> explain.
See D-014 for invented-parameter interception.
See D-016 for the retry/backoff, max-turns, and failure-handling guardrails.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass

import duckdb
import groq
from groq import Groq

from retail_memory.agent.prompts import SYSTEM_PROMPT_V1
from retail_memory.agent.schemas import ALL_TOOLS
from retail_memory.tools.markdown import recommend_markdown
from retail_memory.tools.sales_summary import get_sales_summary

MODEL = "openai/gpt-oss-120b"

MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
MAX_TOOL_CALLS_PER_QUESTION = 1

TOOL_FUNCTIONS = {
    "get_sales_summary": get_sales_summary,
    "recommend_markdown": recommend_markdown,
}

PARAM_LABELS = {
    "product_id": "the product ID",
    "start_week": "the starting week",
    "end_week": "the ending week",
    "margin": "the assumed margin",
}


@dataclass(frozen=True)
class AgentResponse:
    question: str
    status: str  # "answered", "clarification_needed", "declined", "service_unavailable"
    tool_called: str | None
    tool_args: dict | None
    invented_params: list[str]
    final_text: str


def _value_appears_in_text(value, text: str) -> bool:
    """Over-conservative check: is this value literally present in the question?"""
    text_lower = text.lower()
    if isinstance(value, float) and 0 < value < 1:
        pct = int(round(value * 100))
        if f"{pct}%" in text_lower or f"{pct} %" in text_lower:
            return True
    return str(value) in re.findall(r"\d+", text) or str(value).lower() in text_lower


def _invented_params(args: dict, question: str) -> list[str]:
    return [k for k, v in args.items() if not _value_appears_in_text(v, question)]


def _call_with_retry(fn, max_attempts: int = MAX_RETRY_ATTEMPTS):
    """Retry a Groq call on rate limiting with exponential backoff (NFR8)."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except groq.RateLimitError:
            if attempt == max_attempts - 1:
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))


def answer_question(con: duckdb.DuckDBPyConnection, client: Groq, question: str) -> AgentResponse:
    """Public entry point. Handles timeouts and connection errors distinctly
    from rate limits (which retry inside _answer_question_inner)."""
    try:
        return _answer_question_inner(con, client, question)
    except groq.APITimeoutError as e:
        return AgentResponse(question, "service_unavailable", None, None, [],
                              f"Groq API timed out: {e}")
    except groq.APIConnectionError as e:
        return AgentResponse(question, "service_unavailable", None, None, [],
                              f"Could not connect to Groq API: {e}")


def _answer_question_inner(
    con: duckdb.DuckDBPyConnection, client: Groq, question: str
) -> AgentResponse:
    response = _call_with_retry(
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_V1},
                {"role": "user", "content": question},
            ],
            tools=ALL_TOOLS,
            tool_choice="auto",
        )
    )
    msg = response.choices[0].message

    if not msg.tool_calls:
        return AgentResponse(question, "declined", None, None, [], msg.content or "")

    if len(msg.tool_calls) > MAX_TOOL_CALLS_PER_QUESTION:
        return AgentResponse(
            question, "declined", None, None, [],
            f"Model requested {len(msg.tool_calls)} tool calls; this agent supports "
            f"{MAX_TOOL_CALLS_PER_QUESTION} per question for now.",
        )

    call = msg.tool_calls[0]
    args = json.loads(call.function.arguments)
    invented = _invented_params(args, question)

    if invented:
        labels = [PARAM_LABELS.get(p, p) for p in invented]
        joined = " and ".join(labels)
        clarification = (
            f"I'd need to assume {joined} since you didn't specify "
            f"{'it' if len(labels) == 1 else 'them'} -- could you confirm, or should "
            f"I proceed with a reasonable default?"
        )
        return AgentResponse(question, "clarification_needed", call.function.name, args,
                              invented, clarification)

    tool_fn = TOOL_FUNCTIONS[call.function.name]
    result = tool_fn(con, **args)
    result_json = json.dumps(asdict(result), default=str)

    follow_up = _call_with_retry(
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_V1},
                {"role": "user", "content": question},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": result_json,
                },
            ],
            tools=ALL_TOOLS,
        )
    )

    return AgentResponse(question, "answered", call.function.name, args, [],
                          follow_up.choices[0].message.content or "")