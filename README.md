# retail-memory

[![CI](https://github.com/ishitacodes67/retail-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/ishitacodes67/retail-memory/actions/workflows/ci.yml)

An AI agent that tells you when a discount is working, and when it is quietly eating your own sales.

> Status: Week 4 complete. Tools implemented, tested, and validated on real data. Ready for deployment.

## The problem

A shop puts a product on 20% discount. Sales jump. The manager calls it a success.

It usually isn't that simple. Three things get in the way:

1. **Higher units don't mean higher profit.** A discount cuts the margin on every unit sold. Sell twice as many at half the profit per unit, and profit hasn't moved — you've just done more work.
2. **The right comparison isn't "before vs. during."** Promotions are usually scheduled when demand is already high — holidays, paydays, weekends. Comparing promo sales to last week's sales confuses the promo effect with the season.
3. **Some of the lift is stolen, not created.** A promo on one product often pulls customers away from a neighboring product instead of bringing new ones in. Total category sales barely move, but one item looks like a winner.

This project builds an LLM agent that answers these questions using causal inference and rigorous statistical guardrails.

## What it does

The agent routes natural-language questions to one of three Python tools. The LLM never does math; it only chooses tools and explains their outputs.

- `get_sales_summary(product, period)`: Returns total units, revenue, average price, and promo counts.
- `recommend_markdown(product, margin)`: Uses price elasticity to recommend a discount depth that maximizes profit, or refuses if demand is inelastic.
- `detect_cannibalization(promoted_product, neighbor)`: Uses a continuous-depth regression with week fixed effects to measure if a promo on A stole sales from B.

## Architecture & Guardrails

The project is built in four progressive stages, each with its own guardrails:

1. **Data Layer**: Raw CSVs loaded into DuckDB. Aggregated to `product_week` and `product_store_week`. A lightweight `demo.duckdb` (63 MB) is built for deployment, containing zero raw transaction data (complying with dataset terms).
2. **Elasticity**: Naive OLS → Two-way Fixed Effects. Refuses if the covariance matrix is negative/NaN, if quantity is degenerate (bulk items), or if the CI doesn't clear practical significance.
3. **Agent**: Groq tool-calling with Pydantic schemas. Features code-side interception of invented parameters, retry/backoff for rate limits, and a `multi_intent_blocked` guardrail. Evaluated against 22 stable test questions (100% pass).
4. **Cannibalization**: Uses Difference-in-Differences when possible. Because the retailer runs category-wide campaigns (all strawberries on sale at once), it falls back to a continuous-depth regression. Refuses if pre-trends diverge, depths are highly correlated, or variance is invalid.

## Dataset

**Dunnhumby "The Complete Journey"** — household-level grocery transactions with discount, coupon, and display fields per product, per store, per week. Public on Kaggle.

The raw data is not redistributed in this repo. `scripts/build_demo_db.py` creates the deployable demo database from aggregated tables only.

## Results

- **Elasticity**: Of 30 high-volume candidates, only 5 had statistically reliable elasticity estimates, and all 5 were inelastic (e.g., milk at -0.71). The tool correctly refuses to recommend discounts for these products.
- **Cannibalization**: Tested 1127831 vs 860299 (both strawberries). The DiD approach failed due to category-wide promotions. The continuous-depth regression found no statistically significant effect (-0.047, CI [-0.129, 0.034]).
- **Evals**: 22/22 agent eval questions pass (21 clean, 1 documented limitation regarding multi-intent questions).

## Roadmap

- [x] Week 0: repo scaffold, CI, living docs
- [x] Week 1: DuckDB, SQL, `get_sales_summary`
- [x] Week 2: elasticity (naive vs fixed), `recommend_markdown`, backtest
- [x] Week 3: Groq tool-calling agent, evals, guardrails
- [x] Week 4: cannibalization (DiD failure → continuous depth fix)
- [ ] Week 5: FastAPI, Streamlit, Docker, deploy
- [ ] Week 6: docs, demo video, blog post

## Limitations

- **Sparsity**: Only 2,500 households, so per-store variation is noisy.
- **Category-wide promos**: The retailer runs lockstep campaigns, making clean DiD impossible for cannibalization.
- **Multi-intent questions**: The agent can currently only handle one tool call per question; compound questions are safely blocked with a clarification message.