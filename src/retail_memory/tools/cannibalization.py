"""FR3: detect_cannibalization. See docs/requirements.md and D-021/D-022."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import duckdb
import numpy as np
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

MIN_SHARED_STORES = 20
MAX_DEPTH_CORRELATION = 0.95
MIN_PRETREND_CORRELATION = 0.3
BORDERLINE_MARGIN = 0.05
CI_LEVEL = 0.95
MIN_OBSERVATIONS = 30


@dataclass(frozen=True)
class CannibalizationEstimate:
    promoted_product_id: int
    neighbor_product_id: int
    status: str
    coefficient: float | None
    ci_low: float | None
    ci_high: float | None
    ci_level: float | None
    confidence: str
    depth_correlation: float | None
    n_shared_stores: int
    n_observations: int
    notes: list[str]


def _undefined(value: object) -> bool:
    """True for SQL NULL and for NaN (float / numpy / Decimal).

    Used for every statistical check so an undefined result routes to an
    explicit refusal instead of an assumed default.
    """
    return value is None or value != value


def _refuse(
    promoted_product_id: int,
    neighbor_product_id: int,
    status: str,
    notes: list[str],
    *,
    depth_correlation: float | None = None,
    n_shared_stores: int = 0,
    n_observations: int = 0,
) -> CannibalizationEstimate:
    """Build a refusal estimate in one place.

    All refusals share the same shape: coefficient / CIs / ci_level are
    None, confidence is "insufficient_data". Callers pass only the fields
    that have been calculated by the time the refusal occurs.
    """
    return CannibalizationEstimate(
        promoted_product_id,
        neighbor_product_id,
        status,
        None,
        None,
        None,
        None,
        "insufficient_data",
        depth_correlation,
        n_shared_stores,
        n_observations,
        notes,
    )


def _get_shared_stores(
    con: duckdb.DuckDBPyConnection, id_a: int, id_b: int
) -> int:
    query = """
        SELECT COUNT(*) FROM (
            SELECT DISTINCT store_id FROM product_store_week WHERE product_id = ?
            INTERSECT
            SELECT DISTINCT store_id FROM product_store_week WHERE product_id = ?
        )
    """
    return con.execute(query, parameters=[id_a, id_b]).fetchone()[0]


def _get_depth_correlation(
    con: duckdb.DuckDBPyConnection, id_a: int, id_b: int
) -> float | None:
    query = """
        WITH a_data AS (
            SELECT store_id, week_no, discount_depth AS depth_A
            FROM product_store_week WHERE product_id = ?
        ),
        b_data AS (
            SELECT store_id, week_no, discount_depth AS depth_B
            FROM product_store_week WHERE product_id = ?
        )
        SELECT CORR(a.depth_A, COALESCE(b.depth_B, 0)) AS corr
        FROM a_data a
        INNER JOIN (SELECT DISTINCT store_id FROM b_data) b_stores
            ON a.store_id = b_stores.store_id
        LEFT JOIN b_data b
            ON a.store_id = b.store_id AND a.week_no = b.week_no
    """
    res = con.execute(query, parameters=[id_a, id_b]).fetchone()[0]
    if _undefined(res):
        return None
    return res


def _get_pretrend_correlation(
    con: duckdb.DuckDBPyConnection, id_a: int, id_b: int
) -> float | None:
    query = """
        WITH promo_weeks AS (
            SELECT DISTINCT week_no AS pw FROM product_store_week
            WHERE product_id = ? AND is_price_promo AND NOT is_featured
        ),
        pre_weeks AS (
            SELECT DISTINCT p.pw AS promo_week, w.week_no AS pre_week
            FROM promo_weeks p
            JOIN product_week w ON w.week_no BETWEEN p.pw - 4 AND p.pw - 1
        ),
        pre_period AS (
            SELECT a.store_id, a.week_no,
                   a.total_quantity AS qty_a, b.total_quantity AS qty_b
            FROM product_store_week a
            JOIN product_store_week b
              ON a.store_id = b.store_id AND a.week_no = b.week_no
            JOIN pre_weeks pw ON a.week_no = pw.pre_week
            WHERE a.product_id = ? AND b.product_id = ?
        ),
        raw_corrs AS (
            SELECT store_id, CORR(qty_a, qty_b) AS corr
            FROM pre_period
            GROUP BY store_id
            HAVING COUNT(*) >= 4
        ),
        store_corrs AS (
            SELECT store_id, corr
            FROM raw_corrs
            WHERE NOT isnan(corr)
        )
        SELECT MEDIAN(corr) FROM store_corrs
    """
    res = con.execute(query, parameters=[id_a, id_a, id_b]).fetchone()[0]
    if _undefined(res):
        return None
    return res


def detect_cannibalization(
    con: duckdb.DuckDBPyConnection,
    promoted_product_id: int,
    neighbor_product_id: int,
) -> CannibalizationEstimate:
    notes: list[str] = []

    n_stores = _get_shared_stores(con, promoted_product_id, neighbor_product_id)
    if n_stores < MIN_SHARED_STORES:
        notes.append(
            f"Only {n_stores} shared stores found "
            f"(need >= {MIN_SHARED_STORES})."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "insufficient_data",
            notes,
            n_shared_stores=n_stores,
        )

    corr = _get_depth_correlation(con, promoted_product_id, neighbor_product_id)
    if _undefined(corr):
        notes.append(
            "Could not compute depth correlation "
            "(zero variance or no data). Refusing."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "insufficient_data",
            notes,
            n_shared_stores=n_stores,
        )
    if corr > MAX_DEPTH_CORRELATION:
        notes.append(
            f"Discount depth correlation is {corr:.3f} "
            f"(max allowed {MAX_DEPTH_CORRELATION}). "
            "Category-wide lockstep makes separation impossible."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "refused_correlated",
            notes,
            depth_correlation=float(corr),
            n_shared_stores=n_stores,
        )

    pretrend_corr = _get_pretrend_correlation(
        con, promoted_product_id, neighbor_product_id
    )
    if _undefined(pretrend_corr):
        notes.append(
            "Pre-trend check could not be computed "
            "(insufficient store overlap or zero variance). Refusing."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "insufficient_data",
            notes,
            depth_correlation=float(corr),
            n_shared_stores=n_stores,
        )

    if pretrend_corr < MIN_PRETREND_CORRELATION:
        notes.append(
            f"Median pre-trend correlation is {pretrend_corr:.3f} "
            f"(min required {MIN_PRETREND_CORRELATION}). "
            "Neighbor's sales did not trend similarly in a majority of "
            "stores."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "refused_pretrend",
            notes,
            depth_correlation=float(corr),
            n_shared_stores=n_stores,
        )
    if abs(pretrend_corr - MIN_PRETREND_CORRELATION) < BORDERLINE_MARGIN:
        notes.append(
            f"Pre-trend correlation ({pretrend_corr:.3f}) is close to "
            f"the {MIN_PRETREND_CORRELATION} threshold; treat this "
            "control's validity as uncertain."
        )

    query = """
        WITH a_data AS (
            SELECT store_id, week_no, total_quantity AS qty_A,
                   discount_depth AS depth_A
            FROM product_store_week WHERE product_id = ?
        ),
        b_data AS (
            SELECT store_id, week_no, total_quantity AS qty_B,
                   discount_depth AS depth_B
            FROM product_store_week WHERE product_id = ?
        )
        SELECT a.store_id, a.week_no, a.qty_A, a.depth_A,
               COALESCE(b.qty_B, 0) AS qty_B,
               COALESCE(b.depth_B, 0) AS depth_B
        FROM a_data a
        INNER JOIN (SELECT DISTINCT store_id FROM b_data) b_stores
            ON a.store_id = b_stores.store_id
        LEFT JOIN b_data b
            ON a.store_id = b.store_id AND a.week_no = b.week_no
    """
    df = con.execute(
        query, parameters=[promoted_product_id, neighbor_product_id]
    ).df()

    if len(df) < MIN_OBSERVATIONS:
        notes.append(
            f"Only {len(df)} observations "
            f"(need >= {MIN_OBSERVATIONS}). Insufficient data."
        )
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "insufficient_data",
            notes,
            depth_correlation=float(corr),
            n_shared_stores=n_stores,
            n_observations=len(df),
        )

    df["log_B_qty"] = np.log(df["qty_B"] + 1)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = smf.ols(
                "log_B_qty ~ depth_A + depth_B + C(week_no)",
                data=df,
            ).fit(
                cov_type="cluster",
                cov_kwds={"groups": df["store_id"]},
            )

            if any(
                issubclass(w.category, SingularMatrixWarning) for w in caught
            ):
                notes.append(
                    "Rank-deficient design matrix "
                    "(SingularMatrixWarning). Refusing."
                )
                return _refuse(
                    promoted_product_id,
                    neighbor_product_id,
                    "insufficient_data",
                    notes,
                    depth_correlation=float(corr),
                    n_shared_stores=n_stores,
                    n_observations=len(df),
                )

            cov_diag = np.diag(model.cov_params())
            if (
                (cov_diag < 0).any()
                or np.isnan(cov_diag).any()
                or np.isinf(cov_diag).any()
            ):
                notes.append(
                    "Negative or NaN variance in covariance matrix. "
                    "Standard errors are invalid; refusing."
                )
                return _refuse(
                    promoted_product_id,
                    neighbor_product_id,
                    "insufficient_data",
                    notes,
                    depth_correlation=float(corr),
                    n_shared_stores=n_stores,
                    n_observations=len(df),
                )

            coef = model.params["depth_A"]
            ci = model.conf_int().loc["depth_A"]

            if (
                len(ci) != 2
                or np.isnan(ci[0])
                or np.isnan(ci[1])
                or np.isnan(coef)
            ):
                notes.append(
                    "Confidence interval or coefficient is NaN. Refusing."
                )
                return _refuse(
                    promoted_product_id,
                    neighbor_product_id,
                    "insufficient_data",
                    notes,
                    depth_correlation=float(corr),
                    n_shared_stores=n_stores,
                    n_observations=len(df),
                )

            ci_low, ci_high = ci[0], ci[1]
    except Exception as e:
        notes.append(f"Regression failed to converge: {e}")
        return _refuse(
            promoted_product_id,
            neighbor_product_id,
            "insufficient_data",
            notes,
            depth_correlation=float(corr),
            n_shared_stores=n_stores,
            n_observations=len(df),
        )

    excludes_zero = (ci_low > 0) or (ci_high < 0)
    confidence = "high" if excludes_zero else "low"
    if not excludes_zero:
        notes.append(
            "CI includes zero. Cannot distinguish the effect from zero."
        )

    return CannibalizationEstimate(
        promoted_product_id,
        neighbor_product_id,
        "estimated",
        float(coef),
        float(ci_low),
        float(ci_high),
        CI_LEVEL,
        confidence,
        float(corr),
        n_stores,
        len(df),
        notes,
    )