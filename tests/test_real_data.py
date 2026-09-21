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