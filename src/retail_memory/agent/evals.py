"""Eval harness: run the question set, score tool-call correctness (NFR5)."""

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
        ))
    return results


def summarize(results: list[EvalResult]) -> str:
    n_pass = sum(r.passed for r in results)
    lines = [f"{'PASS' if r.passed else 'FAIL'}  {r.id}: {r.reason}" for r in results]
    lines.append(f"\n{n_pass}/{len(results)} passed ({n_pass/len(results):.0%})")
    return "\n".join(lines)