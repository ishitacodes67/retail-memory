"""Derive a product x store x week promo table from the loaded raw tables.

Defines what counts as a "promo week" for a product in a store:

  - is_price_promo: the volume-weighted discount off list price that week is at
    least `threshold`. Threshold chosen as 0.35; see docs/decisions.md, D-004.
  - is_featured: the product had any row in causal_data that week in that store
    (a display or mailer placement). This is a coarse signal on its own (see
    docs/data-notes.md, Day 3 Test C) and is kept as a secondary flag, not the
    primary promo definition.

Run after retail_memory.data.load.build_database:

    python -m retail_memory.data.promo
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/processed/retail.duckdb")
DEFAULT_THRESHOLD = 0.35


def build_promo_table(con: duckdb.DuckDBPyConnection, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Create/replace the `product_store_week` table. Returns its row count.

    Requires `transactions` and `causal` to already exist (see
    retail_memory.data.load.build_database). retail_disc is clipped to at most
    zero before use (D-003): a handful of rows carry an anomalous positive value,
    and without clipping that produces a negative, nonsensical list price.
    """
    con.execute(
        """
        CREATE OR REPLACE TABLE product_store_week AS
        WITH clean AS (
            SELECT
                product_id, store_id, week_no, quantity, sales_value,
                sales_value - LEAST(retail_disc, 0) AS list_value
            FROM transactions
            WHERE quantity > 0 AND sales_value > 0
        ),
        weekly AS (
            SELECT
                product_id, store_id, week_no,
                SUM(quantity) AS total_quantity,
                SUM(sales_value) AS net_revenue,
                SUM(list_value) AS list_revenue,
                COUNT(*) AS n_transactions,
                1 - (SUM(sales_value) / NULLIF(SUM(list_value), 0)) AS discount_depth
            FROM clean
            GROUP BY product_id, store_id, week_no
        )
        SELECT
            w.*,
            w.discount_depth >= ? AS is_price_promo,
            c.product_id IS NOT NULL AS is_featured
        FROM weekly w
        LEFT JOIN causal c
            ON w.product_id = c.product_id
           AND w.store_id = c.store_id
           AND w.week_no = c.week_no
        """,
        [threshold],
    )
    return con.sql("SELECT COUNT(*) FROM product_store_week").fetchone()[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the product_store_week promo table.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    con = duckdb.connect(str(args.db_path))
    try:
        n = build_promo_table(con, args.threshold)
    finally:
        con.close()
    print(f"Built product_store_week: {n:,} rows (threshold={args.threshold:.0%})")


if __name__ == "__main__":
    main()