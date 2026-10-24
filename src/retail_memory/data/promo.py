"""Derive product x store x week and product x week promo tables from the loaded raw tables."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path("data/processed/retail.duckdb")
DEFAULT_THRESHOLD = 0.35


def build_promo_table(con: duckdb.DuckDBPyConnection, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Create/replace the `product_store_week` table."""
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
    """Create/replace `product_week`: one row per product per week, summed across all stores."""
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
            COALESCE(f.any_price_promo, 0) = 1 AS is_price_promo_any_store,
            COALESCE(f.any_featured, 0) = 1 AS is_featured
        FROM weekly w
        LEFT JOIN store_flags f
            ON w.product_id = f.product_id
           AND w.week_no = f.week_no
        """,
    )
    return con.sql("SELECT COUNT(*) FROM product_week").fetchone()[0]


def build_quantity_profile_table(con: duckdb.DuckDBPyConnection) -> int:
    """One row per product: share of transactions with quantity=1 (D-008 guardrail input)."""
    con.execute("""
        CREATE OR REPLACE TABLE product_quantity_profile AS
        SELECT product_id,
               COUNT(*) AS n_transactions,
               AVG((quantity = 1)::INT) AS pct_quantity_eq_1
        FROM transactions
        WHERE quantity > 0
        GROUP BY product_id
    """)
    return con.sql("SELECT COUNT(*) FROM product_quantity_profile").fetchone()[0]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the promo tables.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    con = duckdb.connect(str(args.db_path))
    try:
        n_psw = build_promo_table(con, args.threshold)
        n_pw = build_product_week_table(con, args.threshold)
        n_profile = build_quantity_profile_table(con)
    finally:
        con.close()
    print(f"Built product_store_week: {n_psw:,} rows (threshold={args.threshold:.0%})")
    print(f"Built product_week:       {n_pw:,} rows (threshold={args.threshold:.0%})")
    print(f"Built product_quantity_profile: {n_profile:,} rows")


if __name__ == "__main__":
    main()