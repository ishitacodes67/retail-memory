"""Eval harness: run the question set, score tool-call correctness (NFR5).

Limitation: scores tool_called and tool_args only, not response text.
A response with the right tool and the right args but a broken explanation
still passes. The ci_level fabrication bug (D-016) would have passed this
harness -- the wrong percentage appeared in the explanation, not the tool call.
Response-text quality is a separate, not-yet-built eval dimension.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
from groq import Groq

from retail_memory.agent.loop import answer_question

DEFAULT_EVAL_PATH = Path("evals/questions.jsonl")


@dataclass(frozen=True)
class EvalResult:
    id: str
    question: str
    passed: bool
    reason: str
    actual_tool: str | None
    actual_args: dict | None
    known_limitation: str | None = None  # from the case's own field, if any


def _score(expected_tool, expected_args, actual_tool, actual_args) -> tuple[bool, str]:
    if expected_tool != actual_tool:
        return False, f"expected tool {expected_tool!r}, got {actual_tool!r}"
    if expected_args is None:
        return True, "tool match, no specific args required"
    if actual_args is None:
        return False, "expected args but none were produced"
    mismatches = {
        k: (v, actual_args.get(k)) for k, v in expected_args.items() if actual_args.get(k) != v
    }
    if mismatches:
        return False, f"arg mismatches: {mismatches}"
    return True, "exact match"


def run_evals(
    con: duckdb.DuckDBPyConnection, client: Groq, path: Path = DEFAULT_EVAL_PATH
) -> list[EvalResult]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    results = []
    for case in cases:
        response = answer_question(con, client, case["question"])
        passed, reason = _score(
            case.get("expected_tool"), case.get("expected_args"),
            response.tool_called, response.tool_args,
        )
        results.append(EvalResult(
            case["id"], case["question"], passed, reason,
            response.tool_called, response.tool_args,
            case.get("known_limitation"),
        ))
    return results


def summarize(results: list[EvalResult]) -> str:
    n_pass = sum(r.passed for r in results)
    n_limited = sum(r.passed and r.known_limitation is not None for r in results)
    n_clean = n_pass - n_limited
    lines = [f"{'PASS' if r.passed else 'FAIL'}  {r.id}: {r.reason}" for r in results]
    lines.append(
        f"\n{n_pass}/{len(results)} passed ({n_pass/len(results):.0%}) -- "
        f"{n_clean} clean, {n_limited} passing against a documented known "
        f"limitation (see known_limitation field). Scores tool-call correctness "
        f"only, not response text."
    )
    return "\n".join(lines)