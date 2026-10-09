"""Tests for estimate_elasticity, covering each guardrail and branch."""

import duckdb
import numpy as np
import pytest

from retail_memory.tools.elasticity import estimate_elasticity

N_WEEKS, N_STORES = 40, 20


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE product (product_id BIGINT, curr_size_of_product VARCHAR)")
    connection.execute("""CREATE TABLE product_week (
        product_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo_any_store BOOLEAN, is_featured BOOLEAN)""")
    connection.execute("""CREATE TABLE product_store_week (
        product_id BIGINT, store_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo BOOLEAN, is_featured BOOLEAN)""")
    connection.execute("CREATE TABLE transactions (product_id BIGINT, store_id BIGINT, "
                        "week_no BIGINT, quantity BIGINT, sales_value DOUBLE, retail_disc DOUBLE)")

    rng = np.random.default_rng(0)

    connection.execute("INSERT INTO product VALUES (100, '12 OZ')")
    rows_sw, rows_txn = [], []
    for w in range(N_WEEKS):
        for s in range(N_STORES):
            q = int(rng.integers(5, 20))
            price = round(float(rng.uniform(1.0, 2.0)), 2)
            rows_sw.append((100, s, w, q, q * price, q * price, 1, 0.0, False, False))
            rows_txn.append((100, s, w, q, q * price, 0.0))
    connection.executemany("INSERT INTO product_store_week VALUES (?,?,?,?,?,?,?,?,?,?)", rows_sw)
    connection.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?)", rows_txn)

    connection.execute("INSERT INTO product VALUES (200, '40 LB')")
    rows_txn2 = [(200, s, w, 1, round(float(rng.uniform(5, 8)), 2), 0.0)
                 for w in range(N_WEEKS) for s in range(N_STORES)]
    connection.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?)", rows_txn2)

    connection.execute("INSERT INTO product VALUES (300, '1 LB')")
    connection.executemany(
        "INSERT INTO transactions VALUES (?,?,?,?,?,?)",
        [(300, 1, w, 5, 10.0, 0.0) for w in range(2)],
    )

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