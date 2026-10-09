"""FR2: recommend_markdown. Built on estimate_elasticity.
See D-010 for the pricing formula and why it refuses when it does.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from retail_memory.tools.elasticity import estimate_elasticity

RECENT_WEEKS_FOR_CURRENT_PRICE = 4


@dataclass(frozen=True)
class MarkdownRecommendation:
    product_id: int
    margin: float
    status: str  # "recommended", "no_discount_indicated", "insufficient_data"
    elasticity: float | None
    elasticity_ci: tuple[float, float] | None
    current_price: float | None
    recommended_price: float | None
    recommended_discount_depth: float | None
    was_clipped_to_historical_range: bool
    predicted_profit_change: float | None
    predicted_profit_change_range: tuple[float, float] | None
    notes: list[str]


def _current_price(con, product_id: int) -> float | None:
    """Volume-weighted price over the most recent N weeks."""
    row = con.sql(
        f"""
        WITH recent AS (
            SELECT week_no, net_revenue, total_quantity
            FROM product_week
            WHERE product_id = ?
            ORDER BY week_no DESC
            LIMIT {RECENT_WEEKS_FOR_CURRENT_PRICE}
        )
        SELECT SUM(net_revenue) / SUM(total_quantity) FROM recent
        """,
        params=[product_id],
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _historical_max_discount_depth(con, product_id: int) -> float:
    row = con.sql(
        "SELECT MAX(discount_depth) FROM product_week WHERE product_id = ?",
        params=[product_id],
    ).fetchone()
    return row[0] if row and row[0] is not None else 0.0


def _profit_ratio(price: float, cost: float, elasticity: float, baseline_price: float) -> float:
    """Profit at `price` relative to profit at `baseline_price`, under constant elasticity."""
    baseline_cost_margin = baseline_price - cost
    if baseline_cost_margin <= 0:
        return float("nan")
    return ((price - cost) / baseline_cost_margin) * (price / baseline_price) ** elasticity


def recommend_markdown(
    con: duckdb.DuckDBPyConnection, product_id: int, margin: float
) -> MarkdownRecommendation:
    notes: list[str] = []

    if not (0 < margin < 1):
        raise ValueError(f"margin must be between 0 and 1, got {margin}")

    est = estimate_elasticity(con, product_id)

    if est.method == "refused" or est.confidence == "insufficient_data":
        reason = "; ".join(est.notes)
        notes.append(f"estimate_elasticity refused or had insufficient data: {reason}")
        return MarkdownRecommendation(
            product_id, margin, "insufficient_data", None, None, None, None, None,
            False, None, None, notes,
        )

    if est.confidence == "low":
        notes.append(
            f"Elasticity CI [{est.ci_low:.3f}, {est.ci_high:.3f}] includes zero. "
            f"Cannot confidently say price affects demand for this product at all, "
            f"so no markdown recommendation is offered."
        )
        return MarkdownRecommendation(
            product_id, margin, "insufficient_data", est.coefficient,
            (est.ci_low, est.ci_high), None, None, None, False, None, None, notes,
        )

    e = est.coefficient
    current_price = _current_price(con, product_id)
    if current_price is None:
        notes.append("Could not determine a current price.")
        return MarkdownRecommendation(
            product_id, margin, "insufficient_data", e, (est.ci_low, est.ci_high),
            None, None, None, False, None, None, notes,
        )

    if abs(e) <= 1:
        notes.append(f"Demand is inelastic (e={e:.3f}, |e|<=1): a markdown is never "
                      f"profit-optimal under this model.")
        return MarkdownRecommendation(
            product_id, margin, "no_discount_indicated", e, (est.ci_low, est.ci_high),
            current_price, None, None, False, None, None, notes,
        )

    optimal_margin = 1 / abs(e)
    if optimal_margin >= margin:
        notes.append(f"Elasticity-implied optimal margin ({optimal_margin:.1%}) is at or "
                      f"above the current margin ({margin:.1%}): current pricing is already "
                      f"favorable; no markdown indicated.")
        return MarkdownRecommendation(
            product_id, margin, "no_discount_indicated", e, (est.ci_low, est.ci_high),
            current_price, None, None, False, None, None, notes,
        )

    cost = current_price * (1 - margin)
    recommended_price = cost / (1 - optimal_margin)
    discount_depth = 1 - recommended_price / current_price

    max_historical = _historical_max_discount_depth(con, product_id)
    clipped = discount_depth > max_historical
    if clipped:
        notes.append(f"Recommended discount ({discount_depth:.1%}) exceeds the deepest "
                      f"discount ever observed for this product ({max_historical:.1%}); "
                      f"clipped to the historical range.")
        discount_depth = max_historical
        recommended_price = current_price * (1 - discount_depth)

    profit_point = _profit_ratio(recommended_price, cost, e, current_price) - 1
    profit_low = _profit_ratio(recommended_price, cost, est.ci_low, current_price) - 1
    profit_high = _profit_ratio(recommended_price, cost, est.ci_high, current_price) - 1

    return MarkdownRecommendation(
        product_id, margin, "recommended", e, (est.ci_low, est.ci_high),
        current_price, recommended_price, discount_depth, clipped,
        profit_point, (min(profit_low, profit_high), max(profit_low, profit_high)), notes,
    )