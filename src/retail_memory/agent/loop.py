"""The real agent loop: route -> validate params -> execute -> explain.
See D-014 for invented-parameter interception.
See D-016 for the retry/backoff, max-turns, and failure-handling guardrails.
See D-017 for temperature=0 (eval determinism).
See D-018 for system_prompt parameterization and structured logging.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("retail_memory.agent")

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
    # One of: answered, clarification_needed, declined, service_unavailable, tool_error
    status: str
    tool_called: str | None
    tool_args: dict | None
    invented_params: list[str]
    final_text: str
    tool_result: dict | None = None


def _value_appears_in_text(value, text: str) -> bool:
    text_lower = text.lower()
    if isinstance(value, float) and 0 < value < 1:
        pct = int(round(value * 100))
        if f"{pct}%" in text_lower or f"{pct} %" in text_lower:
            return True
    return str(value) in re.findall(r"\d+", text) or str(value).lower() in text_lower


def _invented_params(args: dict, question: str) -> list[str]:
    return [k for k, v in args.items() if not _value_appears_in_text(v, question)]


def _call_with_retry(fn, max_attempts: int = MAX_RETRY_ATTEMPTS):
    for attempt in range(max_attempts):
        try:
            return fn()
        except groq.RateLimitError:
            if attempt == max_attempts - 1:
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))


def answer_question(
    con: duckdb.DuckDBPyConnection,
    client: Groq,
    question: str,
    system_prompt: str = SYSTEM_PROMPT_V1,
) -> AgentResponse:
    try:
        return _answer_question_inner(con, client, question, system_prompt)
    except groq.APITimeoutError as e:
        return AgentResponse(question, "service_unavailable", None, None, [],
                              f"Groq API timed out: {e}")
    except groq.APIConnectionError as e:
        return AgentResponse(question, "service_unavailable", None, None, [],
                              f"Could not connect to Groq API: {e}")


def _answer_question_inner(
    con: duckdb.DuckDBPyConnection,
    client: Groq,
    question: str,
    system_prompt: str,
) -> AgentResponse:
    response = _call_with_retry(
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            tools=ALL_TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
            temperature=0,
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
    start = time.monotonic()
    try:
        result = tool_fn(con, **args)
    except ValueError as e:
        return AgentResponse(
            question, "tool_error", call.function.name, args, [],
            f"The tool couldn't process that request: {e}",
        )
    latency = round((time.monotonic() - start) * 1000)
    logger.info(
        f"tool_call: {call.function.name} args={args} latency_ms={latency} "
        f"status={getattr(result, 'status', None)}"
    )
    result_dict = asdict(result)
    result_json = json.dumps(result_dict, default=str)

    follow_up = _call_with_retry(
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
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
            parallel_tool_calls=False,
            temperature=0,
        )
    )

    follow_up_msg = follow_up.choices[0].message
    if follow_up_msg.tool_calls:
        second_tool = follow_up_msg.tool_calls[0].function.name
        return AgentResponse(
            question, "multi_intent_blocked", call.function.name, args, [],
            f"I executed {call.function.name} for the first part of your question. "
            f"The model then tried to call {second_tool} for a second part, but this "
            f"agent supports one tool call per question. Please ask about the second "
            f"part separately.",
            result_dict,
        )
    return AgentResponse(
        question, "answered", call.function.name, args, [],
        follow_up_msg.content or "",
        result_dict,
    )
from retail_memory.tools.cannibalization import detect_cannibalization

TOOL_FUNCTIONS = {
    "get_sales_summary": get_sales_summary,
    "recommend_markdown": recommend_markdown,
    "detect_cannibalization": detect_cannibalization,
}