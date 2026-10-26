# Requirements

What this project must do, and what it must not do. Written before implementation, so the code has something to be measured against.

## Functional requirements

### FR1: get_sales_summary

- **Inputs:** a product identifier and a time window (start week, end week).
- **Output:** total units, total revenue, average price, and the count of weeks in that window where `is_price_promo` is true (from `product_store_week`, defined as volume-weighted discount depth >= 0.35 in D-004), with `is_featured` reported separately.
- **Failure behavior:** if the product does not exist, return a clear error naming the missing product. If the window has fewer than 4 weeks of data, return the summary but label it low confidence. If the product has no sales in the window, return zeros with a "no sales" note, not an empty result.
the number of weeks in that window where `is_price_promo` is true (from `product_store_week`, defined as volume-weighted discount depth >= 0.35 in D-004), with `is_featured` reported separately

### FR2: recommend_markdown

- **Inputs:** a product identifier and an assumed gross margin as a percentage.
- **Output:** a recommended discount depth, a predicted profit change versus no discount, a confidence interval around that change, and a confidence label ("high", "low", or "insufficient data").
- **Failure behavior:** if the elasticity estimate has too few observations, return "insufficient data" instead of a recommendation. If margin is missing or out of range (0 to 1), refuse. Never recommend a discount depth the historical data never covered.

### FR3: detect_cannibalization

- **Inputs:** a promoted product and a candidate neighbor product.
- **Output:** the estimated shift in **units of the neighbor product** during the promo, a confidence interval, and whether the effect is statistically distinguishable from zero.
- **Failure behavior:** if the neighbor's pre-promo sales don't trend similarly to the promoted product, refuse and explain that the control is unsuitable. If there are fewer than 4 pre-promo weeks, return "insufficient data". If both products were promoted simultaneously, refuse — the comparison is not valid.
- **Note:** an earlier naive version (before/after only) is built and deliberately shown to fail in `notebooks/`, before this final contract is implemented.
### FR4: Agent

- **Does:** routes a natural-language question to one of the three tools, calls the tool, and explains the result in plain language using only numbers returned by the tool.
- **Must never do:** compute numbers itself, invent a product ID, claim a causal effect the tool did not return, or answer a question that falls outside the three tools. When uncertain, it must say "I can't answer that with the available tools".

## Non-functional requirements

| ID | Requirement | Target | How I'll check |
|----|-------------|--------|----------------|
| NFR1 | Tool determinism | Same inputs give same outputs, every time | Run each tool twice on the same inputs in a test |
| NFR2 | Tool latency (local) | TBD, measure first | Time 20 calls on the full dataset, report median and p95 |
| NFR3 | Agent latency | TBD, measure first | Time 10 questions end-to-end, report median |
| NFR4 | Test coverage on tools | Every tool has at least one success case and one failure case | Count tests, review `tests/` |
| NFR5 | Agent eval pass rate | At least 80% of eval questions hit the expected tool call | Run the eval set, record the score |
| NFR6 | Reproducibility | One command from a clean clone installs and passes tests | `pip install -r requirements-dev.txt && pytest` in CI on every push |
| NFR7 | Testability without the LLM | Every tool is unit-testable with no LLM, no network, no API key | Run `pytest` with `GROQ_API_KEY` unset — all tool tests still pass |
| NFR8 | Rate-limit tolerance | Agent retries on HTTP 429 and fails gracefully after N attempts | Mock a 429 in a test; verify retry then clear error |
| NFR9 | Secrets hygiene | No API key, `.env`, or credential ever committed | `git log --all -- .env` returns nothing; CI checks `.env` is gitignored |
| NFR10 | Data hygiene | Raw dataset never committed; only small samples if licensed for it | Repo size stays under 5 MB; `.gitignore` covers `data/raw/*` |

## Edge cases

| Case | Expected behavior |
|------|-------------------|
| Too few weeks of sales | Return "insufficient data", do not estimate |
| No price variation in window | Refuse elasticity estimate — cannot identify a slope |
| No promo variation in window | Refuse elasticity estimate — no treatment to compare against |
| Zero-sale weeks missing from transaction log | Fill with zero rows before fitting; never silently drop them |
| Zero or negative quantity rows | Exclude with a logged count; a negative return is not a sale |
| Zero or negative sales_value rows | Exclude; log the count in the tool's output metadata |
| Ambiguous or nonexistent product name | Return a "did you mean" list of nearest product names, or a clear "not found" |
| Both products promoted at once | Refuse cannibalization — no valid control |
| Product with no history | Return "no sales in window", do not error |
| Promo week with zero sales on the promoted item | Flag as anomaly, exclude from elasticity fit |
| Neighbor is identical to promoted product | Refuse — cannibalization needs two distinct products |
| Requested window crosses dataset start or end | Clamp to available range, note the clamp in the output |
| Margin of exactly 0% | Refuse — no profit to protect |
| Neighbor trends in opposite direction pre-promo | Refuse and explain the control is unsuitable |
| Out-of-scope question to the agent | Reply "I can't answer that with the available tools", do not call any tool |
| LLM produces numbers without calling a tool | Reject the response; require a tool call before returning any number |
| Groq API timeout | Retry once, then return "service unavailable" with no fabricated answer |

## Out of scope

- Real-time pricing or live updates. This is a batch analysis tool.
- Multi-store price optimization.
- Product recommendation or cross-sell modeling.
- Data collection. The tool works on the Dunnhumby dataset only.
- Any profit number that depends on real cost data — margin is assumed, not measured.
- Causal inference outside the diff-in-diff design. No regression discontinuity, no synthetic control.
- A production database. DuckDB on local files is enough for this project.

## Success criteria (provisional)

- All three tools have passing unit tests, including every failure case listed above.
- The agent answers at least 80% of eval questions with the correct tool call.
- The naive "before vs. during" cannibalization detector fails on the placebo test; the diff-in-diff version passes.
- Backtest error (MAPE on held-out, later-in-time promos): target under 20%, provisional, measured at the discount depth actually applied. If the data does not support that, report the actual number honestly.
- Every NFR is measured and the result written into the README's Results section. No NFR stays "TBD" at the end.
- The final demo runs end-to-end with a live agent, a FastAPI backend, and a Streamlit UI.