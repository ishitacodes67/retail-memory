"""FR3: detect_cannibalization. See docs/requirements.md and D-021/D-022."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import duckdb
import numpy as np
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

MIN_SHARED_STORES = 20
MAX_DEPTH_CORRELATION = 0.95
MIN_PRETREND_CORRELATION = 0.3
CI_LEVEL = 0.95


@dataclass(frozen=True)
class CannibalizationEstimate:
    promoted_product_id: int
    neighbor_product_id: int
    status: str  # "estimated", "refused_correlated", "refused_pretrend", "insufficient_data"
    coefficient: float | None
    ci_low: float | None
    ci_high: float | None
    ci_level: float | None
    confidence: str  # "high" or "low"
    depth_correlation: float | None
    n_shared_stores: int
    n_observations: int
    notes: list[str]


def _get_shared_stores(con: duckdb.DuckDBPyConnection, id_a: int, id_b: int) -> int:
    query = f"""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT store_id FROM product_store_week WHERE product_id = {id_a}
            INTERSECT
            SELECT DISTINCT store_id FROM product_store_week WHERE product_id = {id_b}
        )
    """
    return con.sql(query).fetchone()[0]


def _get_depth_correlation(con: duckdb.DuckDBPyConnection, id_a: int, id_b: int) -> float | None:
    query = f"""
        WITH promo_weeks AS (
            SELECT DISTINCT week_no FROM product_store_week
            WHERE product_id = {id_a} AND is_price_promo AND NOT is_featured
        ),
        a_depth AS (
            SELECT week_no, AVG(discount_depth) AS d_a FROM product_store_week
            WHERE product_id = {id_a} AND week_no IN (SELECT week_no FROM promo_weeks) GROUP BY week_no
        ),
        b_depth AS (
            SELECT week_no, AVG(discount_depth) AS d_b FROM product_store_week
            WHERE product_id = {id_b} AND week_no IN (SELECT week_no FROM promo_weeks) GROUP BY week_no
        )
        SELECT CORR(d_a, d_b) FROM a_depth JOIN b_depth USING (week_no)
    """
    res = con.sql(query).fetchone()[0]
    if res is not None and math.isnan(res):
        return 1.0
    return res


def _get_pretrend_correlation(con: duckdb.DuckDBPyConnection, id_a: int, id_b: int) -> float | None:
    """Check if the neighbor's sales trended similarly to the promoted product 
    in the 4 weeks before each promo week."""
    query = f"""
        WITH promo_weeks AS (
            SELECT DISTINCT week_no AS pw FROM product_store_week
            WHERE product_id = {id_a} AND is_price_promo AND NOT is_featured
        ),
        pre_weeks AS (
            SELECT DISTINCT p.pw AS promo_week, w.week_no AS pre_week
            FROM promo_weeks p
            JOIN product_week w ON w.week_no BETWEEN p.pw - 4 AND p.pw - 1
        )
        SELECT CORR(a.total_quantity, COALESCE(b.total_quantity, 0))
        FROM pre_weeks pw
        JOIN product_week a ON a.week_no = pw.pre_week AND a.product_id = {id_a}
        LEFT JOIN product_week b ON b.week_no = pw.pre_week AND b.product_id = {id_b}
    """
    res = con.sql(query).fetchone()[0]
    if res is not None and math.isnan(res):
        return 1.0
    return res


def detect_cannibalization(
    con: duckdb.DuckDBPyConnection, promoted_product_id: int, neighbor_product_id: int
) -> CannibalizationEstimate:
    notes: list[str] = []
    
    # Guardrail 1: Shared stores
    n_stores = _get_shared_stores(con, promoted_product_id, neighbor_product_id)
    if n_stores < MIN_SHARED_STORES:
        notes.append(f"Only {n_stores} shared stores found (need >= {MIN_SHARED_STORES}).")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "insufficient_data",
            None, None, None, None, "insufficient_data", None, n_stores, 0, notes
        )

    # Guardrail 2: Depth correlation
    corr = _get_depth_correlation(con, promoted_product_id, neighbor_product_id)
    if corr is not None and corr > MAX_DEPTH_CORRELATION:
        notes.append(f"Discount depth correlation is {corr:.3f} (max allowed {MAX_DEPTH_CORRELATION}). "
                     f"Category-wide lockstep makes separation impossible.")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "refused_correlated",
            None, None, None, None, "insufficient_data", corr, n_stores, 0, notes
        )

    # Guardrail 3: Pre-trend correlation
    pretrend_corr = _get_pretrend_correlation(con, promoted_product_id, neighbor_product_id)
    if pretrend_corr is not None and pretrend_corr < MIN_PRETREND_CORRELATION:
        notes.append(f"Pre-trend correlation is {pretrend_corr:.3f} (min required {MIN_PRETREND_CORRELATION}). "
                     f"Neighbor's sales did not trend similarly to the promoted product before the promo.")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "refused_pretrend",
            None, None, None, None, "insufficient_data", corr, n_stores, 0, notes
        )

    # Guardrail 4: Regression with Singular Matrix check
    query = f"""
        WITH a_data AS (
            SELECT store_id, week_no, total_quantity AS qty_A, discount_depth AS depth_A
            FROM product_store_week WHERE product_id = {promoted_product_id}
        ),
        b_data AS (
            SELECT store_id, week_no, total_quantity AS qty_B, discount_depth AS depth_B
            FROM product_store_week WHERE product_id = {neighbor_product_id}
        )
        SELECT 
            a.store_id, a.week_no, a.qty_A, a.depth_A,
            COALESCE(b.qty_B, 0) AS qty_B, COALESCE(b.depth_B, 0) AS depth_B
        FROM a_data a
        INNER JOIN (SELECT DISTINCT store_id FROM b_data) b_stores ON a.store_id = b_stores.store_id
        LEFT JOIN b_data b ON a.store_id = b.store_id AND a.week_no = b.week_no
    """
    df = con.sql(query).df()
    if len(df) < 30:
        notes.append(f"Only {len(df)} observations. Insufficient data.")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "insufficient_data",
            None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
        )

    df["log_B_qty"] = np.log(df["qty_B"] + 1)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            model = smf.ols("log_B_qty ~ depth_A + depth_B + C(week_no)", data=df).fit(
                cov_type="cluster", cov_kwds={"groups": df["store_id"]}
            )
            singular = any(issubclass(w.category, SingularMatrixWarning) for w in caught)
        except Exception as e:
            notes.append(f"Regression failed to converge: {e}")
            return CannibalizationEstimate(
                promoted_product_id, neighbor_product_id, "insufficient_data",
                None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
            )

    if singular:
        notes.append("Rank-deficient design matrix (SingularMatrixWarning). Refusing.")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "insufficient_data",
            None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
        )

    coef = model.params["depth_A"]
    ci_low, ci_high = model.conf_int().loc["depth_A"]
    excludes_zero = (ci_low > 0) or (ci_high < 0)
    confidence = "high" if excludes_zero else "low"
    if not excludes_zero:
        notes.append("CI includes zero. Cannot distinguish the effect from zero.")

    return CannibalizationEstimate(
        promoted_product_id, neighbor_product_id, "estimated",
        float(coef), float(ci_low), float(ci_high), CI_LEVEL,
        confidence, float(corr) if corr is not None else None,
        n_stores, len(df), notes
    )