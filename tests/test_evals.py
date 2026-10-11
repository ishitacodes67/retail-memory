"""Unit tests for the eval scoring function. Pure logic, no API calls."""

from retail_memory.agent.evals import _score


def test_exact_match_passes():
    passed, _ = _score(
        "get_sales_summary",
        {"product_id": 1},
        "get_sales_summary",
        {"product_id": 1},
    )
    assert passed


def test_wrong_tool_fails():
    passed, _ = _score("recommend_markdown", None, "get_sales_summary", {})
    assert not passed


def test_no_args_required_passes_regardless_of_actual_args():
    passed, _ = _score("get_sales_summary", None, "get_sales_summary", {"product_id": 1})
    assert passed


def test_missing_expected_arg_fails():
    passed, _ = _score("get_sales_summary", {"product_id": 1}, "get_sales_summary", {})
    assert not passed