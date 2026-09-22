"""Tests for the promo-week table, using small synthetic transactions covering
every combination of price cut and feature."""

import duckdb
import pytest

from retail_memory.data.promo import build_promo_table

THRESHOLD = 0.10


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE transactions (
        product_id BIGINT, store_id BIGINT, week_no BIGINT,
        quantity BIGINT, sales_value DOUBLE, retail_disc DOUBLE)""")
    connection.execute("""CREATE TABLE causal (
        product_id BIGINT, store_id BIGINT, week_no BIGINT,
        display VARCHAR, mailer VARCHAR)""")

    rows = [
        (10, 5, 1, 1, 2.00, 0.0),    # no discount, but featured
        (11, 5, 1, 1, 1.60, -0.40),  # clean 20% price cut, not featured
        (12, 5, 1, 1, 2.00, 3.99),   # anomalous positive retail_disc (D-003)
        (13, 5, 1, 1, 1.50, -0.50),  # 25% price cut AND featured (confounded)
        (14, 5, 1, 1, 2.00, 0.0),    # neither
    ]
    connection.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?)", rows)
    connection.executemany(
        "INSERT INTO causal VALUES (?,?,?,?,?)",
        [(10, 5, 1, "3", "0"), (13, 5, 1, "0", "A")],
    )
    yield connection
    connection.close()


def _row(con, product_id):
    return con.sql(
        f"SELECT discount_depth, is_price_promo, is_featured "
        f"FROM product_store_week WHERE product_id = {product_id}"
    ).fetchone()


def test_row_count(con):
    assert build_promo_table(con, THRESHOLD) == 5


def test_featured_without_discount(con):
    build_promo_table(con, THRESHOLD)
    depth, is_promo, is_featured = _row(con, 10)
    assert depth == 0
    assert is_promo is False
    assert is_featured is True


def test_clean_price_cut(con):
    build_promo_table(con, THRESHOLD)
    depth, is_promo, is_featured = _row(con, 11)
    assert depth == pytest.approx(0.20)
    assert is_promo is True
    assert is_featured is False


def test_anomalous_positive_retail_disc_is_clipped(con):
    build_promo_table(con, THRESHOLD)
    depth, is_promo, is_featured = _row(con, 12)
    assert depth == 0          # not a 200% "discount"
    assert is_promo is False
    assert is_featured is False


def test_confounded_price_cut_and_feature(con):
    build_promo_table(con, THRESHOLD)
    depth, is_promo, is_featured = _row(con, 13)
    assert depth == pytest.approx(0.25)
    assert is_promo is True
    assert is_featured is True


def test_neither_promo_nor_featured(con):
    build_promo_table(con, THRESHOLD)
    depth, is_promo, is_featured = _row(con, 14)
    assert is_promo is False
    assert is_featured is False


def test_rebuild_replaces_old_table(con):
    build_promo_table(con, THRESHOLD)
    n = build_promo_table(con, THRESHOLD)
    assert n == 5  # not 10: CREATE OR REPLACE, not appended