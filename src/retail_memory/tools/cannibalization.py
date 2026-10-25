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
    return con.execute(query).fetchone()[0]


def _get_depth_correlation(con: duckdb.DuckDBPyConnection, id_a: int, id_b: int) -> float | None:
    """Calculate the correlation of depths on the exact same full panel 
    used by the regression (all weeks A was sold, matched stores, B filled with 0)."""
    query = f"""
        WITH a_data AS (
            SELECT store_id, week_no, discount_depth AS depth_A
            FROM product_store_week WHERE product_id = {id_a}
        ),
        b_data AS (
            SELECT store_id, week_no, discount_depth AS depth_B
            FROM product_store_week WHERE product_id = {id_b}
        )
        SELECT CORR(a.depth_A, COALESCE(b.depth_B, 0)) AS corr
        FROM a_data a
        INNER JOIN (SELECT DISTINCT store_id FROM b_data) b_stores 
            ON a.store_id = b_stores.store_id
        LEFT JOIN b_data b 
            ON a.store_id = b.store_id 
           AND a.week_no = b.week_no
    """
    res = con.execute(query).fetchone()[0]
    if res is not None and math.isnan(res):
        return 1.0
    return res


def _get_pretrend_correlation(con: duckdb.DuckDBPyConnection, id_a: int, id_b: int) -> float | None:
    """Check if the neighbor's sales trended similarly to the promoted product 
    in the 4 weeks before each promo week. Returns the median store-level correlation
    to avoid Simpson's Paradox (pooling masking divergent store-level trends)."""
    query = f"""
        WITH promo_weeks AS (
            SELECT DISTINCT week_no AS pw FROM product_store_week
            WHERE product_id = {id_a} AND is_price_promo AND NOT is_featured
        ),
        pre_weeks AS (
            SELECT DISTINCT p.pw AS promo_week, w.week_no AS pre_week
            FROM promo_weeks p
            JOIN product_week w ON w.week_no BETWEEN p.pw - 4 AND p.pw - 1
        ),
        pre_period AS (
            SELECT a.store_id, a.week_no, a.total_quantity AS qty_a, b.total_quantity AS qty_b
            FROM product_store_week a
            JOIN product_store_week b ON a.store_id = b.store_id AND a.week_no = b.week_no
            JOIN pre_weeks pw ON a.week_no = pw.pre_week
            WHERE a.product_id = {id_a} AND b.product_id = {id_b}
        ),
        store_corrs AS (
            SELECT store_id, CORR(qty_a, qty_b) AS corr
            FROM pre_period
            GROUP BY store_id
            HAVING COUNT(*) >= 4
        )
        SELECT MEDIAN(corr) FROM store_corrs
    """
    res = con.execute(query).fetchone()[0]
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
        notes.append(
            f"Discount depth correlation is {corr:.3f} "
            f"(max allowed {MAX_DEPTH_CORRELATION}). "
            f"Category-wide lockstep makes separation impossible."
        )
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "refused_correlated",
            None, None, None, None, "insufficient_data", corr, n_stores, 0, notes
        )

    # Guardrail 3: Pre-trend correlation (median store-level)
    pretrend_corr = _get_pretrend_correlation(con, promoted_product_id, neighbor_product_id)
    if pretrend_corr is not None and pretrend_corr < MIN_PRETREND_CORRELATION:
        notes.append(
            f"Median pre-trend correlation is {pretrend_corr:.3f} "
            f"(min required {MIN_PRETREND_CORRELATION}). "
            f"Neighbor's sales did not trend similarly to the promoted product "
            f"in a majority of stores."
        )
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "refused_pretrend",
            None, None, None, None, "insufficient_data", corr, n_stores, 0, notes
        )

    # Guardrail 4: Regression with Singular Matrix AND Negative Variance check
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
    df = con.execute(query).df()
    if len(df) < 30:
        notes.append(f"Only {len(df)} observations. Insufficient data.")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "insufficient_data",
            None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
        )

    df["log_B_qty"] = np.log(df["qty_B"] + 1)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = smf.ols("log_B_qty ~ depth_A + depth_B + C(week_no)", data=df).fit(
                cov_type="cluster", cov_kwds={"groups": df["store_id"]}
            )
            
            # 1. Catch Rank Deficiency (SingularMatrixWarning)
            if any(issubclass(w.category, SingularMatrixWarning) for w in caught):
                notes.append("Rank-deficient design matrix (SingularMatrixWarning). Refusing.")
                return CannibalizationEstimate(
                    promoted_product_id, neighbor_product_id, "insufficient_data",
                    None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
                )
            
            # 2. Deterministic check for numerical instability (Negative Variance)
            cov_diag = np.diag(model.cov_params())
            if (cov_diag < 0).any() or np.isnan(cov_diag).any() or np.isinf(cov_diag).any():
                notes.append("Negative or NaN variance in covariance matrix. "
                             "Standard errors are invalid; refusing.")
                return CannibalizationEstimate(
                    promoted_product_id, neighbor_product_id, "insufficient_data",
                    None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
                )

            coef = model.params["depth_A"]
            ci = model.conf_int().loc["depth_A"]
            
            # 3. Catch NaN Confidence Intervals
            if len(ci) != 2 or np.isnan(ci[0]) or np.isnan(ci[1]) or np.isnan(coef):
                notes.append("Confidence interval or coefficient is NaN. Refusing.")
                return CannibalizationEstimate(
                    promoted_product_id, neighbor_product_id, "insufficient_data",
                    None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
                )
                
            ci_low, ci_high = ci[0], ci[1]
            
    except Exception as e:
        notes.append(f"Regression failed to converge: {e}")
        return CannibalizationEstimate(
            promoted_product_id, neighbor_product_id, "insufficient_data",
            None, None, None, None, "insufficient_data", corr, n_stores, len(df), notes
        )

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