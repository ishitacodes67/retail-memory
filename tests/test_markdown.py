"""Tests for recommend_markdown (FR2). estimate_elasticity is mocked here since it
already has its own tests in test_elasticity.py -- this file tests the pricing
logic, refusal rules, and clipping on their own."""

import duckdb
import pytest

from retail_memory.tools import markdown as markdown_module
from retail_memory.tools.elasticity import ElasticityEstimate
from retail_memory.tools.markdown import recommend_markdown


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE product_week (
        product_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo_any_store BOOLEAN, is_featured BOOLEAN)""")
    rows = [
        (100, 1, 100, 50.0, 50.0, 100, 0.20, False, False),   # old week: sets historical max
        (100, 2, 100, 143.0, 143.0, 100, 0.0, False, False),
        (100, 3, 100, 143.0, 143.0, 100, 0.0, False, False),
        (100, 4, 100, 143.0, 143.0, 100, 0.0, False, False),
        (100, 5, 100, 143.0, 143.0, 100, 0.0, False, False),  # most recent
    ]
    connection.executemany("INSERT INTO product_week VALUES (?,?,?,?,?,?,?,?,?)", rows)
    yield connection
    connection.close()


def _fake(method, coefficient, ci_low, ci_high, confidence):
    return ElasticityEstimate(
        product_id=100, method=method, coefficient=coefficient,
        ci_low=ci_low, ci_high=ci_high, confidence=confidence,
        n_weeks=50, df_resid=100, notes=[],
    )


def test_invalid_margin_raises(con):
    with pytest.raises(ValueError, match="margin"):
        recommend_markdown(con, 100, margin=1.5)


def test_refused_elasticity_propagates(con, monkeypatch):
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("refused", None, None, None, "insufficient_data"))
    result = recommend_markdown(con, 100, margin=0.3)
    assert result.status == "insufficient_data"


def test_low_confidence_refuses(con, monkeypatch):
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("two_way_fe", -0.2, -0.5, 0.1, "low"))
    result = recommend_markdown(con, 100, margin=0.3)
    assert result.status == "insufficient_data"
    assert any("includes zero" in n for n in result.notes)


def test_inelastic_gives_no_discount(con, monkeypatch):
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("two_way_fe", -0.6, -0.8, -0.4, "high"))
    result = recommend_markdown(con, 100, margin=0.3)
    assert result.status == "no_discount_indicated"
    assert any("inelastic" in n for n in result.notes)


def test_already_optimal_gives_no_discount(con, monkeypatch):
    # e=-2 -> optimal_margin=0.50; current margin 0.30 is already below that
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("two_way_fe", -2.0, -3.0, -1.0, "high"))
    result = recommend_markdown(con, 100, margin=0.3)
    assert result.status == "no_discount_indicated"


def test_happy_path_recommends_markdown(con, monkeypatch):
    # e=-5, margin=0.30 -> optimal_margin=0.20 < 0.30: markdown indicated
    # current_price = 1.43 (last 4 weeks only -- see fixture)
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("two_way_fe", -5.0, -6.0, -4.0, "high"))
    result = recommend_markdown(con, 100, margin=0.3)
    assert result.status == "recommended"
    assert result.recommended_discount_depth == pytest.approx(0.125, abs=0.01)
    assert result.predicted_profit_change > 0
    assert not result.was_clipped_to_historical_range


def test_clips_to_historical_range(con, monkeypatch):
    # e=-20 -> optimal_margin=0.05, huge implied discount, but the deepest
    # discount ever observed (from the old week) is only 0.20
    monkeypatch.setattr(markdown_module, "estimate_elasticity",
        lambda c, p: _fake("two_way_fe", -20.0, -25.0, -15.0, "high"))
    result = recommend_markdown(con, 100, margin=0.5)
    assert result.was_clipped_to_historical_range
    assert result.recommended_discount_depth == pytest.approx(0.20, abs=0.001)