"""Tests for recommend_markdown. Branches driven by mocked elasticity where needed."""

from unittest.mock import patch

import duckdb
import pytest

from retail_memory.tools.elasticity import ElasticityEstimate
from retail_memory.tools.markdown import recommend_markdown


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE product (product_id BIGINT, curr_size_of_product VARCHAR)")
    c.execute("""CREATE TABLE product_week (
        product_id BIGINT, week_no BIGINT, total_quantity BIGINT, net_revenue DOUBLE,
        list_revenue DOUBLE, n_transactions BIGINT, discount_depth DOUBLE,
        is_price_promo_any_store BOOLEAN, is_featured BOOLEAN)""")
    c.execute("""CREATE TABLE product_store_week (
        product_id BIGINT, store_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo BOOLEAN, is_featured BOOLEAN)""")
    c.execute("CREATE TABLE transactions (product_id BIGINT, store_id BIGINT, week_no BIGINT, "
              "quantity BIGINT, sales_value DOUBLE, retail_disc DOUBLE)")
    c.execute("INSERT INTO product VALUES (100, '12 OZ')")
    # 40 weeks of price 1.50, quantity 20 -> current_price = 1.50
    rows = [(100, w, 20, 30.0, 30.0, 1, 0.0, False, False) for w in range(40)]
    c.executemany("INSERT INTO product_week VALUES (?,?,?,?,?,?,?,?,?)", rows)
    # historical max discount depth 0.30 (so the clip test fires)
    c.execute("UPDATE product_week SET discount_depth = 0.30 WHERE week_no = 1")
    yield c
    c.close()


def _mock_est(**kw):
    defaults = dict(
        product_id=100, method="two_way_fe", coefficient=-2.5,
        ci_low=-3.0, ci_high=-2.0, confidence="high",
        n_weeks=40, df_resid=200, notes=[],
    )
    defaults.update(kw)
    return ElasticityEstimate(**defaults)


def test_margin_out_of_range_raises(con):
    with pytest.raises(ValueError):
        recommend_markdown(con, 100, 0.0)
    with pytest.raises(ValueError):
        recommend_markdown(con, 100, 1.0)


@patch("retail_memory.tools.markdown.estimate_elasticity")
def test_low_confidence_refuses(mock_est, con):
    mock_est.return_value = _mock_est(confidence="low")
    r = recommend_markdown(con, 100, 0.5)
    assert r.status == "insufficient_data"
    assert r.recommended_discount_depth is None


@patch("retail_memory.tools.markdown.estimate_elasticity")
def test_inelastic_no_discount(mock_est, con):
    mock_est.return_value = _mock_est(coefficient=-0.5, ci_low=-0.8, ci_high=-0.2)
    r = recommend_markdown(con, 100, 0.5)
    assert r.status == "no_discount_indicated"


@patch("retail_memory.tools.markdown.estimate_elasticity")
def test_current_margin_below_optimal_no_discount(mock_est, con):
    # e=-2.5 -> optimal margin = 0.4. Current margin 0.3 is below it.
    mock_est.return_value = _mock_est()
    r = recommend_markdown(con, 100, 0.3)
    assert r.status == "no_discount_indicated"


@patch("retail_memory.tools.markdown.estimate_elasticity")
def test_recommended_when_margin_exceeds_optimal(mock_est, con):
    # e=-2.5 -> optimal margin = 0.4. Current margin 0.5 is above it.
    # Recommended price = cost/(1-0.4) = (1.5*0.5)/0.6 = 1.25, discount 16.7%.
    # Historical max discount is 0.30, so 16.7% < 30%, no clip.
    mock_est.return_value = _mock_est()
    r = recommend_markdown(con, 100, 0.5)
    assert r.status == "recommended"
    assert r.recommended_discount_depth == pytest.approx(1 - 1.25 / 1.5, abs=0.001)
    assert r.was_clipped_to_historical_range is False
    assert r.predicted_profit_change is not None


@patch("retail_memory.tools.markdown.estimate_elasticity")
def test_clip_to_historical_max(mock_est, con):
    # e=-1.2 -> optimal margin = 0.833. Margin 0.9 -> recommended discount is huge,
    # will clip to the historical 0.30.
    mock_est.return_value = _mock_est(coefficient=-1.2, ci_low=-1.5, ci_high=-1.05)
    r = recommend_markdown(con, 100, 0.9)
    assert r.status == "recommended"
    assert r.was_clipped_to_historical_range is True
    assert r.recommended_discount_depth == pytest.approx(0.30, abs=0.001)