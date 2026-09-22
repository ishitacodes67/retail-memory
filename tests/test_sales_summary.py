"""Tests for get_sales_summary (FR1), using a small synthetic product_store_week."""

import duckdb
import pytest

from retail_memory.tools.sales_summary import get_sales_summary


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE product (product_id BIGINT, commodity_desc VARCHAR)")
    connection.execute("CREATE TABLE transactions (product_id BIGINT, week_no BIGINT)")
    connection.execute(
        """CREATE TABLE product_store_week (
            product_id BIGINT, store_id BIGINT, week_no BIGINT,
            total_quantity BIGINT, net_revenue DOUBLE, list_revenue DOUBLE,
            n_transactions BIGINT, discount_depth DOUBLE,
            is_price_promo BOOLEAN, is_featured BOOLEAN)"""
    )
    connection.executemany("INSERT INTO transactions VALUES (?,?)", [(1, 1), (1, 10)])
    connection.execute("INSERT INTO product VALUES (100, 'FLUID MILK PRODUCTS')")
    connection.execute("INSERT INTO product VALUES (200, 'COUPON/MISC ITEMS')")
    connection.execute("INSERT INTO product VALUES (300, 'FLUID MILK PRODUCTS')")
    rows = [
        (100, 1, 3, 10, 20.0, 20.0, 5, 0.0, False, False),
        (100, 1, 4, 10, 16.0, 20.0, 5, 0.2, True, False),
        (100, 1, 5, 10, 20.0, 20.0, 5, 0.0, False, True),
        (100, 1, 6, 10, 15.0, 20.0, 5, 0.25, True, True),
        (100, 1, 7, 10, 20.0, 20.0, 5, 0.0, False, False),
        (200, 1, 5, 3, 9.0, 9.0, 3, 0.0, False, False),
    ]
    connection.executemany(
        "INSERT INTO product_store_week VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    yield connection
    connection.close()


def test_normal_full_data_is_high_confidence(con):
    s = get_sales_summary(con, 100, 1, 10)
    assert s.total_units == 50
    assert s.total_revenue == pytest.approx(91.0)
    assert s.average_price == pytest.approx(1.82)
    assert s.n_product_store_weeks == 5
    assert s.n_distinct_weeks_with_sales == 5
    assert s.n_promo_product_store_weeks == 2
    assert s.confidence == "high"
    assert s.notes == []


def test_sparse_window_is_low_confidence(con):
    s = get_sales_summary(con, 100, 3, 4)
    assert s.n_distinct_weeks_with_sales == 2
    assert s.confidence == "low"
    assert any("Low confidence" in n for n in s.notes)


def test_nonexistent_product_raises(con):
    with pytest.raises(ValueError, match="999"):
        get_sales_summary(con, 999, 1, 10)


def test_product_with_zero_sales_returns_zeros_not_error(con):
    s = get_sales_summary(con, 300, 1, 10)
    assert s.total_units == 0
    assert s.average_price is None
    assert s.confidence == "low"
    assert any("No sales" in n for n in s.notes)


def test_window_beyond_dataset_is_clamped(con):
    s = get_sales_summary(con, 100, 5, 50)
    assert s.window_was_clamped is True
    assert s.start_week == 5
    assert s.end_week == 10
    assert any("clamped" in n for n in s.notes)


def test_coupon_misc_product_is_flagged(con):
    s = get_sales_summary(con, 200, 1, 10)
    assert any("bookkeeping" in n for n in s.notes)


def test_short_calendar_window_is_low_confidence_even_if_fully_sold(con):
    s = get_sales_summary(con, 100, 3, 5)
    assert s.n_distinct_weeks_with_sales == 3  # all 3 calendar weeks had sales
    assert s.confidence == "low"      # but the window itself is < 4 weeks