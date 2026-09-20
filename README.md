# retail-memory

![CI](https://github.com/ishitacodes67/retail-memory/actions/workflows/ci.yml/badge.svg)

An AI agent that tells you when a discount is working, and when it is quietly eating your own sales.

> Status: in progress. Independent implementation, inspired by the reciprocate.you "Retail Memory" workshop.

## The problem

A shop puts a product on 20% discount. Sales jump. The manager calls it a success.

It usually isn't that simple. Three things get in the way:

1. **Higher units don't mean higher profit.** A discount cuts the margin on every unit sold. Sell twice as many at half the profit per unit, and profit hasn't moved — you've just done more work.
2. **The right comparison isn't "before vs. during."** Promotions are usually scheduled when demand is already high — holidays, paydays, weekends. Comparing promo sales to last week's sales confuses the promo effect with the season.
3. **Some of the lift is stolen, not created.** A promo on one product often pulls customers away from a neighboring product instead of bringing new ones in. Total category sales barely move, but one item looks like a winner.

So the real questions are: did *profit* go up, and did the lift come from new sales or stolen ones? This project builds an agent that answers both — and says "I don't know" when the data is too thin.

## What it will do

- `get_sales_summary(product, period)`: a product ID and a time window → total units, total revenue, average price, and the number of weeks in that window that had a promo flag.
- `recommend_markdown(product, margin)`: a product ID and an assumed gross margin → a recommended discount depth, a predicted profit change, a confidence interval, and a confidence label ("high", "low", or "insufficient data").
- `detect_cannibalization(promo_product, neighbor)`: a promoted product and a candidate neighbor → the estimated sales shift on the neighbor, a confidence interval, and whether the effect is statistically distinguishable from zero.

## Design rule

The LLM never does math. It only chooses tools and explains their outputs. Every number comes from tested Python functions that return the same answer every time.

## Dataset

Planned: **Dunnhumby "The Complete Journey"** — household-level grocery transactions with discount, coupon, and display fields per product, per store, per week. Public on Kaggle.

Alternates considered:
- M5 Walmart: daily item-store sales, good for scale, but no discount field
- UCI Online Retail II: simpler, but no promo flags

The raw data is not redistributed in this repo. A download script and `.gitignore` keep it local.

## Roadmap

- [ ] Week 0: repo scaffold, docs, dataset intake
- [ ] Week 1: DuckDB, SQL, `get_sales_summary`
- [ ] Week 2: elasticity (naive vs fixed), `recommend_markdown`, backtest
- [ ] Week 3: rule-based router, Groq tool-calling agent, evals
- [ ] Week 4: cannibalization (naive, broken, diff-in-diff fix, placebo test)
- [ ] Week 5: FastAPI, Streamlit, Docker, deploy
- [ ] Week 6: docs, demo video, blog post

## Results

TBD. Only numbers from my own notebooks will go here — no illustrative figures, no made-up percentages.

## Limitations

TBD. Will cover: the causal assumptions behind the diff-in-diff model, the sample size limits on per-product elasticity estimates, and the fact that the backtest can only check forecast accuracy at the discount depths that were actually used — not depths that were never tried.

## CI

![CI](https://github.com/ishitacodes67/retail-memory/actions/workflows/ci.yml/badge.svg)