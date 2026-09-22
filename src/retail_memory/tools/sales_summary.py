"""FR1: get_sales_summary. See docs/requirements.md and docs/decisions.md (D-003, D-004,
D-005) for the price, promo, and confidence definitions this tool relies on.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

MIN_WEEKS_FOR_HIGH_CONFIDENCE = 4
COUPON_MISC_COMMODITY = "COUPON/MISC ITEMS"


@dataclass(frozen=True)
class SalesSummary:
    """Result of get_sales_summary. All money figures use net price (D-003):
    what the customer actually paid, not list price.

    Counts and grain: `product_store_week` is one row per product x store x week.
    The `n_*` fields below count that grain, NOT calendar weeks. The distinct
    calendar-week count is reported separately as `n_distinct_weeks_with_sales`,
    which is what the confidence rule uses.
    """

    product_id: int
    requested_start_week: int
    requested_end_week: int
    start_week: int
    end_week: int
    window_was_clamped: bool
    total_units: int
    total_revenue: float
    average_price: float | None
    n_product_store_weeks: int
    n_distinct_weeks_with_sales: int
    n_promo_product_store_weeks: int
    n_featured_product_store_weeks: int
    confidence: str  # "high" or "low"
    notes: list[str]


def _dataset_week_range(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    return con.sql("SELECT MIN(week_no), MAX(week_no) FROM transactions").fetchone()


def get_sales_summary(
    con: duckdb.DuckDBPyConnection, product_id: int, start_week: int, end_week: int
) -> SalesSummary:
    """Summarize a product's sales over a week window, across all stores.

    Raises:
        ValueError: if product_id does not exist in the product table.
    """
    if con.sql(
        "SELECT 1 FROM product WHERE product_id = ?", params=[product_id]
    ).fetchone() is None:
        raise ValueError(f"No such product_id: {product_id}")

    notes: list[str] = []
    ds_lo, ds_hi = _dataset_week_range(con)
    clamped_start, clamped_end = max(start_week, ds_lo), min(end_week, ds_hi)
    clamped = (clamped_start, clamped_end) != (start_week, end_week)
    if clamped:
        notes.append(
            f"Requested window {start_week}-{end_week} clamped to available "
            f"data range {clamped_start}-{clamped_end}."
        )

    commodity = con.sql(
        "SELECT commodity_desc FROM product WHERE product_id = ?", params=[product_id]
    ).fetchone()[0]
    if commodity == COUPON_MISC_COMMODITY:
        notes.append(
            "This product_id is a COUPON/MISC bookkeeping line, not a real "
            "purchasable product (see docs/data-notes.md, Day 3 investigation)."
        )

    (
        total_units,
        total_revenue,
        n_psw,
        n_promo,
        n_featured,
        n_distinct_weeks,
    ) = con.sql(
        """
        SELECT SUM(total_quantity), SUM(net_revenue), COUNT(*),
               SUM(is_price_promo::INT), SUM(is_featured::INT),
               COUNT(DISTINCT week_no)
        FROM product_store_week
        WHERE product_id = ? AND week_no BETWEEN ? AND ?
        """,
        params=[product_id, clamped_start, clamped_end],
    ).fetchone()

    if total_units is None:
        notes.append("No sales for this product in the requested window.")
        return SalesSummary(
            product_id, start_week, end_week, clamped_start, clamped_end, clamped,
            0, 0.0, None, 0, 0, 0, 0, "low", notes,
        )

    average_price = total_revenue / total_units if total_units else None
    n_calendar_weeks = clamped_end - clamped_start + 1
    low_confidence = (
        n_distinct_weeks < MIN_WEEKS_FOR_HIGH_CONFIDENCE
        or n_calendar_weeks < MIN_WEEKS_FOR_HIGH_CONFIDENCE
    )
    if low_confidence:
        notes.append(
            f"Low confidence: {n_distinct_weeks} distinct week(s) with sales "
            f"in a {n_calendar_weeks}-week window "
            f"(need >= {MIN_WEEKS_FOR_HIGH_CONFIDENCE} of each)."
        )

    return SalesSummary(
        product_id, start_week, end_week, clamped_start, clamped_end, clamped,
        int(total_units), float(total_revenue), average_price,
        int(n_psw), int(n_distinct_weeks), int(n_promo), int(n_featured),
        "low" if low_confidence else "high", notes,
    )