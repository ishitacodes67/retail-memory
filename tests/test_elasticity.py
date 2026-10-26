"""Tests for estimate_elasticity, covering each guardrail and branch."""

import duckdb
import numpy as np
import pytest

from retail_memory.tools.elasticity import estimate_elasticity

N_WEEKS, N_STORES = 40, 20


@pytest.fixture
def con():
    connection = duckdb.connect()
    
    connection.execute("CREATE TABLE product (product_id BIGINT, commodity_desc VARCHAR)")
    connection.execute("CREATE TABLE transactions (product_id BIGINT, week_no BIGINT)")
    connection.execute(
        """CREATE TABLE product_week (
            product_id BIGINT, week_no BIGINT,
            total_quantity BIGINT, net_revenue DOUBLE, list_revenue DOUBLE,
            n_transactions BIGINT, discount_depth DOUBLE,
            is_price_promo_any_store BOOLEAN, is_featured BOOLEAN)"""
    )
    connection.execute("""CREATE TABLE product_store_week (
        product_id BIGINT, store_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo BOOLEAN, is_featured BOOLEAN)""")
    connection.execute("""CREATE TABLE product_quantity_profile (
        product_id BIGINT, n_transactions BIGINT, pct_quantity_eq_1 DOUBLE)""")

    rng = np.random.default_rng(42)

    # Product 100: normal, 40 weeks, decentralized -> two_way_fe
    connection.execute("INSERT INTO product VALUES (100, 'FLUID MILK')")
    connection.execute("INSERT INTO product_quantity_profile VALUES (100, 100, 0.1)")
    
    rows_pw = [(100, w, 20, 30.0, 30.0, 1, 0.0, False, False) for w in range(1, 41)]
    connection.executemany("INSERT INTO product_week VALUES (?,?,?,?,?,?,?,?,?)", rows_pw)

    rows_sw = []
    for w in range(1, 41):
        for s in range(20):
            # Add random noise to quantity and depth so the regression converges
            qty = int(rng.integers(5, 20))
            depth = float(rng.uniform(0.0, 0.4))
            price = round(float(rng.uniform(1.0, 2.0)), 2)
            rows_sw.append((100, s, w, qty, qty * price, qty * price, 1, depth, False, False))
    connection.executemany("INSERT INTO product_store_week VALUES (?,?,?,?,?,?,?,?,?,?)", rows_sw)

    # Product 200: degenerate quantity -> refused
    connection.execute("INSERT INTO product VALUES (200, '40 LB')")
    connection.execute("INSERT INTO product_quantity_profile VALUES (200, 100, 0.95)")

    # Product 300: too few weeks -> refused
    connection.execute("INSERT INTO product VALUES (300, '1 LB')")
    connection.execute("INSERT INTO product_quantity_profile VALUES (300, 100, 0.1)")
    rows_pw_300 = [(300, w, 10, 20.0, 20.0, 1, 0.0, False, False) for w in range(1, 6)]
    connection.executemany("INSERT INTO product_week VALUES (?,?,?,?,?,?,?,?,?)", rows_pw_300)

    yield connection
    connection.close()


def test_normal_product_fits_two_way_fe(con):
    result = estimate_elasticity(con, 100)
    assert result.method == "two_way_fe"
    assert result.coefficient is not None
    assert result.df_resid > 0


def test_degenerate_quantity_refuses(con):
    result = estimate_elasticity(con, 200)
    assert result.method == "refused"
    assert result.confidence == "insufficient_data"
    assert any("quantity=1" in n for n in result.notes)


def test_too_few_weeks_refuses(con):
    result = estimate_elasticity(con, 300)
    assert result.method == "refused"
    assert result.confidence == "insufficient_data"


def test_nonexistent_product_raises(con):
    with pytest.raises(ValueError, match="999"):
        estimate_elasticity(con, 999)