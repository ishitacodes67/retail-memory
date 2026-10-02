"""Reconciliation against the real database. Skipped when it has not been built."""

from pathlib import Path

import duckdb
import pytest

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "retail.duckdb"

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="run the loader first")

# Row counts recorded in docs/data-notes.md
EXPECTED_ROWS = {
    "transactions": 2_595_732,
    "causal": 36_786_524,
    "product": 92_353,
    "hh_demographic": 801,
    "campaign_desc": 30,
    "campaign_table": 7_208,
    "coupon": 124_548,
    "coupon_redempt": 2_318,
}


@pytest.mark.parametrize("table", EXPECTED_ROWS)
def test_row_counts_match_data_notes(table: str):
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        (count,) = con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()
    assert count == EXPECTED_ROWS[table]


def test_promo_table_exists_and_is_reasonable():
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        n = con.sql("SELECT COUNT(*) FROM product_store_week").fetchone()[0]
        promo_rate = con.sql(
            "SELECT AVG(is_price_promo::INT) FROM product_store_week"
        ).fetchone()[0]
    assert n > 0
    assert 0 < promo_rate < 0.5  # a promo should be a minority of weeks, not the norm


def test_discount_depth_is_always_in_valid_range():
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        lo, hi = con.sql(
            "SELECT MIN(discount_depth), MAX(discount_depth) FROM product_store_week"
        ).fetchone()
    assert lo >= 0
    assert hi < 1


def test_any_store_flag_bound_holds():
    """Permanent guard for the D-006 rename.

    If is_price_promo_any_store means "at least one store's depth >= 0.35", then
    every row flagged False must have its volume-weighted aggregate depth below
    0.35, because a weighted average cannot exceed its largest input. If this
    ever fails, the flag and the threshold have drifted apart.
    """
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        max_when_false = con.sql(
            "SELECT MAX(discount_depth) FROM product_week "
            "WHERE NOT is_price_promo_any_store"
        ).fetchone()[0]
    assert max_when_false < 0.35