"""FR2 groundwork: elasticity estimation. See notebooks/elasticity_naive_vs_fixed.ipynb
for the derivation, and D-006, D-008, D-011 for why this function is shaped this way.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import duckdb
import numpy as np
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

QUANTITY_DEGENERATE_THRESHOLD = 0.90    # D-008: banana case
MIN_WEEKS_FOR_ESTIMATE = 20
NEAR_UNIFORM_PRICE_SD = 0.01            # Day 8 diagnostic threshold
PRACTICAL_SIGNIFICANCE_EPSILON = 0.05   # D-011: CI must clear this band
CI_LEVEL = 0.95  # matches statsmodels' default alpha=0.05


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
    ci_level: float = CI_LEVEL


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


def _fit_checked(formula: str, data, cluster_groups=None):
    """Fit an OLS model; return (model, warning_flag).

    warning_flag is True if a SingularMatrixWarning fired, meaning the design
    matrix was rank-deficient and the coefficients are not uniquely determined.
    Caller should treat that as a refusal, not a valid fit.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if cluster_groups is not None:
            model = smf.ols(formula, data=data).fit(
                cov_type="cluster", cov_kwds={"groups": cluster_groups}
            )
        else:
            model = smf.ols(formula, data=data).fit()
        singular = any(
            issubclass(w.category, SingularMatrixWarning) for w in caught
        )
    return model, singular


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
        model, singular = _fit_checked("log_qty ~ log_price + C(month)", df)
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
        model, singular = _fit_checked(
            "log_qty ~ log_price + C(week_no) + C(store_id)",
            df, cluster_groups=df["store_id"],
        )
        method = "two_way_fe"

    if singular:
        notes.append(
            "Rank-deficient design matrix (SingularMatrixWarning). Coefficients are "
            "not uniquely determined; refusing rather than reporting an unreliable number."
        )
        return ElasticityEstimate(
            product_id, "refused", None, None, None, "insufficient_data",
            n_weeks, int(model.df_resid), notes,
        )

    coef = model.params["log_price"]
    ci_low, ci_high = model.conf_int().loc["log_price"]

    if coef > 0 and ci_low > 0:
        notes.append(
            f"Positive, statistically significant coefficient ({coef:.3f}, "
            f"CI [{ci_low:.3f}, {ci_high:.3f}]). Price and quantity moving together "
            f"is not plausible normal-good demand behavior. Likely a measurement "
            f"issue (D-008) or price endogeneity (D-011). Refusing rather than "
            f"reporting a backwards recommendation."
        )
        return ElasticityEstimate(
            product_id, "refused", None, None, None, "insufficient_data",
            n_weeks, int(model.df_resid), notes,
        )

    excludes_practical_zero = (
        (ci_low > PRACTICAL_SIGNIFICANCE_EPSILON)
        or (ci_high < -PRACTICAL_SIGNIFICANCE_EPSILON)
    )
    confidence = "high" if excludes_practical_zero else "low"
    if not excludes_practical_zero:
        notes.append(
            f"CI [{ci_low:.3f}, {ci_high:.3f}] does not clear the "
            f"+/-{PRACTICAL_SIGNIFICANCE_EPSILON} practical-significance band. "
            f"Treated as low confidence even though it may exclude zero."
        )

    return ElasticityEstimate(
        product_id, method, float(coef), float(ci_low), float(ci_high),
        confidence, n_weeks, int(model.df_resid), notes,
    )