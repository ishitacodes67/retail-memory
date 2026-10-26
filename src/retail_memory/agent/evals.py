"""Eval harness: run the question set, score tool-call correctness (NFR5).
Also scores response-text quality for ci_level consistency (D-016).
"""

from __future__ import annotations

import json
import re
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
    tool_passed: bool
    tool_reason: str
    text_passed: bool
    text_reason: str
    actual_tool: str | None
    actual_args: dict | None
    known_limitation: str | None = None


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

def check_text_quality(final_text: str, tool_result: dict | None) -> tuple[bool, str]:
    """Empty final_text is a failure -- the user got no explanation at all."""
    if not final_text or not final_text.strip():
        return False, "empty final_text"
    return check_ci_level_consistency(final_text, tool_result)

def check_ci_level_consistency(final_text: str, tool_result: dict | None) -> tuple[bool, str]:
    """Flags a stated confidence percentage that doesn't match ci_level (D-016)."""
    stated = re.findall(r'(\d{1,3})\s*%\s*confidence', final_text, flags=re.IGNORECASE)
    if not stated:
        return True, "no confidence percentage stated"
    ci_level = (tool_result or {}).get("ci_level")
    if ci_level is None:
        return False, f"stated {stated}% confidence but no ci_level was available"
    expected = str(int(round(ci_level * 100)))
    bad = [p for p in stated if p != expected]
    if bad:
        return False, f"stated {bad}%, but ci_level is {expected}% -- fabricated"
    return True, f"correctly cites {expected}%"


def run_evals(
    con: duckdb.DuckDBPyConnection, client: Groq, path: Path = DEFAULT_EVAL_PATH
) -> list[EvalResult]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    results = []
    for case in cases:
        response = answer_question(con, client, case["question"])
        tool_passed, tool_reason = _score(
            case.get("expected_tool"), case.get("expected_args"),
            response.tool_called, response.tool_args,
        )
        text_passed, text_reason = check_text_quality(
            response.final_text, response.tool_result
        )
        passed = tool_passed and text_passed
        results.append(EvalResult(
            case["id"], case["question"], passed,
            tool_passed, tool_reason,
            text_passed, text_reason,
            response.tool_called, response.tool_args,
            case.get("known_limitation"),
        ))
    return results


def summarize(results: list[EvalResult]) -> str:
    n_pass = sum(r.passed for r in results)
    n_limited = sum(r.passed and r.known_limitation is not None for r in results)
    n_clean = n_pass - n_limited

    lines = []
    for r in results:
        marker = "PASS" if r.passed else "FAIL"
        detail = r.tool_reason if r.tool_passed else f"TOOL: {r.tool_reason}"
        if not r.text_passed:
            detail += f" | TEXT: {r.text_reason}"
        lines.append(f"{marker}  {r.id}: {detail}")

    lines.append(
        f"\n{n_pass}/{len(results)} passed ({n_pass/len(results):.0%}) -- "
        f"{n_clean} clean, {n_limited} passing against a documented known "
        f"limitation. Scores tool-call correctness and text-level ci_level consistency."
    )
    return "\n".join(lines)