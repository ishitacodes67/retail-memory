"""FR2 groundwork: elasticity estimation. See notebooks/elasticity_naive_vs_fixed.ipynb
for the derivation, and D-006/D-008 for why this function is shaped the way it is.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import statsmodels.formula.api as smf

QUANTITY_DEGENERATE_THRESHOLD = 0.90   # D-008: banana case
MIN_WEEKS_FOR_ESTIMATE = 20
NEAR_UNIFORM_PRICE_SD = 0.01           # Day 8 diagnostic threshold


@dataclass(frozen=True)
class ElasticityEstimate:
    product_id: int
    method: str              # "two_way_fe", "month_fallback", or "refused"
    coefficient: float | None
    ci_low: float | None
    ci_high: float | None
    confidence: str          # "high", "low", or "insufficient_data"
    n_weeks: int
    df_resid: int | None
    notes: list[str]


def _quantity_is_degenerate(con, product_id: int) -> bool:
    total, ones = con.sql(
        "SELECT COUNT(*), SUM((quantity=1)::INT) FROM transactions "
        "WHERE product_id = ? AND quantity > 0",
        params=[product_id],
    ).fetchone()
    return (ones / total) > QUANTITY_DEGENERATE_THRESHOLD if total else True


def _is_centralized_pricing(con, product_id: int) -> bool:
    spread = con.sql(
        """
        WITH store_prices AS (
            SELECT week_no, store_id, net_revenue / total_quantity AS price
            FROM product_store_week WHERE product_id = ?
        )
        SELECT AVG(sd_p) FROM (
            SELECT week_no, STDDEV(price) AS sd_p FROM store_prices GROUP BY week_no
        )
        """,
        params=[product_id],
    ).fetchone()[0]
    return spread is None or spread < NEAR_UNIFORM_PRICE_SD


def estimate_elasticity(con: duckdb.DuckDBPyConnection, product_id: int) -> ElasticityEstimate:
    notes: list[str] = []

    if con.sql("SELECT 1 FROM product WHERE product_id=?", params=[product_id]).fetchone() is None:
        raise ValueError(f"No such product_id: {product_id}")

    if _quantity_is_degenerate(con, product_id):
        notes.append(
            f"Over {QUANTITY_DEGENERATE_THRESHOLD:.0%} of transactions have quantity=1 "
            f"(see D-008). Quantity is not a meaningful unit count for this product; "
            f"refusing to estimate."
        )
        return ElasticityEstimate(
            product_id, "refused", None, None, None, "insufficient_data", 0, None, notes
        )

    n_weeks = con.sql(
        "SELECT COUNT(DISTINCT week_no) FROM transactions WHERE product_id=?",
        params=[product_id],
    ).fetchone()[0]
    if n_weeks < MIN_WEEKS_FOR_ESTIMATE:
        notes.append(f"Only {n_weeks} weeks of sales (need >= {MIN_WEEKS_FOR_ESTIMATE}).")
        return ElasticityEstimate(
            product_id, "refused", None, None, None, "insufficient_data", n_weeks, None, notes
        )

    if _is_centralized_pricing(con, product_id):
        notes.append("Centralized pricing detected (D-006). Using month-dummy fallback, "
                     "not full week+store fixed effects.")
        df = con.sql(
            """
            SELECT week_no,
                   LOG(total_quantity) AS log_qty,
                   LOG(net_revenue / total_quantity) AS log_price
            FROM product_week WHERE product_id=?
            """, params=[product_id],
        ).df()
        df["month"] = ((df["week_no"] - 1) // 4) % 24
        model = smf.ols("log_qty ~ log_price + C(month)", data=df).fit()
        method = "month_fallback"
    else:
        df = con.sql(
            """
            SELECT week_no, store_id, total_quantity,
                   net_revenue / total_quantity AS price
            FROM product_store_week WHERE product_id=?
            """, params=[product_id],
        ).df()
        df["log_qty"] = np.log(df["total_quantity"])
        df["log_price"] = np.log(df["price"])
        model = smf.ols("log_qty ~ log_price + C(week_no) + C(store_id)", data=df).fit(
            cov_type="cluster", cov_kwds={"groups": df["store_id"]}
        )
        method = "two_way_fe"

    coef = model.params["log_price"]
    ci_low, ci_high = model.conf_int().loc["log_price"]
    excludes_zero = (ci_low > 0) or (ci_high < 0)
    confidence = "high" if excludes_zero else "low"
    if not excludes_zero:
        notes.append("CI includes zero: cannot distinguish the effect from zero "
                     "at this sample size.")

    return ElasticityEstimate(
        product_id, method, float(coef), float(ci_low), float(ci_high),
        confidence, n_weeks, int(model.df_resid), notes,
    )