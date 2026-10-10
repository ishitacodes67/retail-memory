"""The real agent loop: route -> validate params -> execute -> explain.
See D-014 for why invented-parameter checking happens here, not in the prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

import duckdb
from groq import Groq

from retail_memory.agent.prompts import SYSTEM_PROMPT_V1
from retail_memory.agent.schemas import ALL_TOOLS
from retail_memory.tools.markdown import recommend_markdown
from retail_memory.tools.sales_summary import get_sales_summary

MODEL = "openai/gpt-oss-120b"

TOOL_FUNCTIONS = {
    "get_sales_summary": get_sales_summary,
    "recommend_markdown": recommend_markdown,
}


@dataclass(frozen=True)
class AgentResponse:
    question: str
    status: str  # "answered", "clarification_needed", "declined"
    tool_called: str | None
    tool_args: dict | None
    invented_params: list[str]
    final_text: str


def _value_appears_in_text(value, text: str) -> bool:
    """Over-conservative check: is this value literally present in the question?

    Known limitation: a legitimate inference (e.g. "first quarter" -> weeks 1-13)
    also gets flagged as invented. Deliberate tradeoff -- false positives cost a
    clarifying question, false negatives cost a wrong answer presented as fact.
    """
    text_lower = text.lower()
    if isinstance(value, float) and 0 < value < 1:
        pct = int(round(value * 100))
        if f"{pct}%" in text_lower or f"{pct} %" in text_lower:
            return True
    return str(value) in re.findall(r"\d+", text) or str(value).lower() in text_lower


def _invented_params(args: dict, question: str) -> list[str]:
    return [k for k, v in args.items() if not _value_appears_in_text(v, question)]


def answer_question(con: duckdb.DuckDBPyConnection, client: Groq, question: str) -> AgentResponse:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_V1},
            {"role": "user", "content": question},
        ],
        tools=ALL_TOOLS,
        tool_choice="auto",
    )
    msg = response.choices[0].message

    if not msg.tool_calls:
        return AgentResponse(question, "declined", None, None, [], msg.content or "")

    call = msg.tool_calls[0]
    args = json.loads(call.function.arguments)
    invented = _invented_params(args, question)

    PARAM_LABELS = {
        "product_id": "the product ID",
        "start_week": "the starting week",
        "end_week": "the ending week",
        "margin": "the assumed margin",
    }

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

    follow_up = client.chat.completions.create(
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

    return AgentResponse(question, "answered", call.function.name, args, [],
                          follow_up.choices[0].message.content or "")