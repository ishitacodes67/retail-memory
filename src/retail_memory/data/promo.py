"""Derive product x store x week and product x week promo tables from the loaded raw tables.

Defines what counts as a "promo week" for a product:

  - is_price_promo: the volume-weighted discount off list price that week is at
    least `threshold`. Threshold chosen as 0.35; see docs/decisions.md, D-004.
  - is_featured: the product had any causal_data row that week (a display or
    mailer placement). Coarse on its own (see docs/data-notes.md, Day 3 Test C);
    kept as a secondary flag, not the primary promo definition.

Builds two tables:

  - product_store_week: one row per product x store x week. Use for anything
    that needs store-level detail (Week 4 cannibalization, diff-in-diff).
  - product_week: one row per product x week, summed across all stores. Use for
    anything that needs a true count of distinct weeks (get_sales_summary,
    elasticity candidate screening). Added in D-006: the previous version of
    get_sales_summary counted store-weeks where it needed calendar weeks.

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


def build_product_week_table(
    con: duckdb.DuckDBPyConnection, threshold: float = DEFAULT_THRESHOLD
) -> int:
    """Create/replace `product_week`: one row per product per week, summed across
    all stores. Use this (not product_store_week) whenever you need a true count
    of distinct weeks -- e.g. get_sales_summary, or screening products for
    elasticity fitting. product_store_week stays the right table for anything
    that needs store-level detail (Week 4 cannibalization).

    Promo and feature flags are defined at the STORE level first, then
    aggregated with ANY: a product is "on promo this week" if at least one store
    had discount_depth >= threshold for it that week. This preserves the
    store-level threshold (D-004) instead of re-applying it to a volume-weighted
    average across all stores, which would dilute the signal -- for a product
    sold at full price in most stores and promoted in a few, the aggregate depth
    falls below the threshold and the promo is lost.

    The `discount_depth` column here is still the aggregate across stores, kept
    for reference. It is NOT the value used for the promo flag. Anything that
    needs the store-level depth should read product_store_week.
    """
    con.execute(
        """
        CREATE OR REPLACE TABLE product_week AS
        WITH clean AS (
            SELECT
                product_id, week_no, quantity, sales_value,
                sales_value - LEAST(retail_disc, 0) AS list_value
            FROM transactions
            WHERE quantity > 0 AND sales_value > 0
        ),
        weekly AS (
            SELECT
                product_id, week_no,
                SUM(quantity) AS total_quantity,
                SUM(sales_value) AS net_revenue,
                SUM(list_value) AS list_revenue,
                COUNT(*) AS n_transactions,
                1 - (SUM(sales_value) / NULLIF(SUM(list_value), 0)) AS discount_depth
            FROM clean
            GROUP BY product_id, week_no
        ),
        store_flags AS (
            SELECT
                product_id, week_no,
                MAX(is_price_promo::INT) AS any_price_promo,
                MAX(is_featured::INT) AS any_featured
            FROM product_store_week
            GROUP BY product_id, week_no
        )
        SELECT
            w.*,
            COALESCE(f.any_price_promo, 0) = 1 AS is_price_promo,
            COALESCE(f.any_featured, 0) = 1 AS is_featured
        FROM weekly w
        LEFT JOIN store_flags f
            ON w.product_id = f.product_id
           AND w.week_no = f.week_no
        """,
    )
    return con.sql("SELECT COUNT(*) FROM product_week").fetchone()[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the promo tables.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    con = duckdb.connect(str(args.db_path))
    try:
        n_psw = build_promo_table(con, args.threshold)
        n_pw = build_product_week_table(con, args.threshold)
    finally:
        con.close()
    print(f"Built product_store_week: {n_psw:,} rows (threshold={args.threshold:.0%})")
    print(f"Built product_week:       {n_pw:,} rows (threshold={args.threshold:.0%})")


if __name__ == "__main__":
    main()