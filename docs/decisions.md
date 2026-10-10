# Decisions log

Every non-obvious choice, with the trade-off. Write each entry when you decide, not weeks later.

## Template

### D-000: Title
- **Date:**
- **Context:** what problem forced a choice?
- **Options considered:**
- **Decision:**
- **Why:**
- **Trade-offs / what I'd revisit:**

---

### D-001: Dataset choice - Dunnhumby "The Complete Journey"
- **Date:** 2026-09-21
- **Context:** The project needs transactional retail data with enough information to estimate price elasticity and detect cannibalization between neighboring products. The dataset must include a promo signal.
- **Options considered:**
  1. **Dunnhumby "The Complete Journey"** - household-level grocery transactions, ~2.6M line items, 92k products, 582 stores, 102 weeks. Has RETAIL_DISC, COUPON_DISC, COUPON_MATCH_DISC columns plus a separate causal_data table with display and mailer flags per product/store/week.
  2. **M5 Walmart** - daily item-store unit sales with weekly prices. Larger, cleaner, great for forecasting. But no explicit promo flag; a discount must be inferred from a price drop, which is noisier.
  3. **UCI Online Retail II** - simpler transactional data (one UK online retailer). Fast to load, but no promo flags, no store dimension, and no way to define a "promo week" without inventing one.
- **Decision:** Dunnhumby "The Complete Journey".
- **Why:**
  - It is the only one of the three with explicit discount columns (RETAIL_DISC, COUPON_DISC, COUPON_MATCH_DISC) alongside sales_value and quantity, so I can reconstruct list and net prices. How these columns combine is still unverified (see data-notes; test on Day 3).
  - causal_data records display and mailer placements per product/store/week, which gives a second, non-price promo signal. Cannibalization detection needs a way to tell when a product was promoted.
  - It has a store dimension (582 stores), so stores where a product was not featured might serve as controls for difference-in-differences. To be tested: whether treatment actually varies across stores within the same week.
  - 102 weeks (about two years) leaves room to hold out later-in-time promos for backtesting.
- **Trade-offs / what I'd revisit:**
  - Only 2,500 households, so per-product weekly unit counts will be sparse, and per-store counts sparser still (582 stores). On Day 3, check how concentrated sales are across stores; store-level controls may need to be grouped.
  - causal_data most likely lists only product-store-weeks that had a display or a mailer (hypothesis: no row = not featured; test on Day 3). So "promo week" is a modeling choice among a price cut, being featured, or both. Decided on Day 4.
  - Odd rows need explicit filters: 14,399 rows with quantity<=0 and sales_value<=0 (most likely returns or voids), 4,451 with quantity>0 and sales_value<=0 (possibly free items), and 67 with quantity<=0 and sales_value>0. Whether revenue summaries are gross or net of returns is still open.
  - Terms: dunnhumby provides the data for classroom and academic use. Raw data stays out of the repo, and I can't assume it may be redistributed in a deployed demo. In Week 5, re-check the terms; the fallback is a demo that ships only derived aggregates if allowed, or otherwise a recorded demo plus local run instructions.
  - Display and mailer placements were not randomly assigned, so this is observational data. Naive before/after comparisons will be biased, and every promo-effect estimate needs a design that handles that (baseline correction, difference-in-differences, placebo tests).
  - Revisit trigger: if product-level elasticity is too noisy at this household scale, first aggregate to sub-commodity level (product.csv has COMMODITY_DESC and SUB_COMMODITY_DESC), then to department if needed. Cost: recommendations then apply to a group of products, not one product. Set the noise threshold after the first elasticity run in Week 2, and keep household-level grain for cannibalization only if it is still workable.
  
---

### D-002: A DuckDB file built by a script, not CSV queries
- **Date:** 2026-09-21
- **Context:** Tools and notebooks need to query 2.6M transaction rows and 36.8M causal rows repeatedly. Querying the raw CSVs every time would be slow and would repeat the same cleaning logic everywhere.
- **Options considered:**
  1. Query the raw CSVs directly with DuckDB's `read_csv` on every call.
  2. Load everything into pandas once per session.
  3. Build a single DuckDB file from the CSVs, and have all downstream code query that file.
- **Decision:** Option 3, built by `python -m retail_memory.data.load`.
- **Why:**
  - One command rebuilds the database from raw CSVs, so the derived artifact always matches the source. Delete and rebuild any time.
  - Queries are fast: DuckDB is columnar and the tables are indexed by scan order.
  - Column names are normalized to lowercase on load, so downstream code never mixes `BASKET_ID` and `basket_id`.
  - Code-like columns (`trans_time`, `display`, `mailer`) are forced to text so leading zeros survive and codes never become numbers.
- **Trade-offs / what I'd revisit:**
  - A few hundred MB of derived data sits on disk. Deleting it costs nothing; a rebuild takes a few minutes.
  - Loading is a build step. If the CSVs change, the database must be rebuilt - there is no auto-sync. That is a deliberate choice: automatic sync would hide mismatches.
  - The 36.8M-row causal table makes the rebuild slow. If it becomes painful, I could load causal as a view over the CSV instead of a table, at the cost of repeated scan time.

---

### D-003: Net unit price as the primary price field
- **Date:** 2026-09-22
- **Context:** Every tool needs a "price" per transaction, and the raw schema offers several candidates: `sales_value / quantity`, `(sales_value - retail_disc) / quantity`, and versions that also add back `coupon_disc` and `coupon_match_disc`. Pick one canonical price that all tools use, so results are consistent.
- **Options considered:**
  1. Net unit price: `sales_value / quantity`. What the customer paid per unit.
  2. List unit price: `(sales_value - retail_disc) / quantity`. Reconstructs shelf price, ignoring coupons.
  3. Full list price: subtract all three discount columns, on the theory that all are inside `sales_value`.
- **Decision:** Use net unit price (`sales_value / quantity`) as the primary price for all tools. Keep the list-price formula provisional and unused unless a tool specifically needs shelf-price comparison.
- **Why:**
  - Net unit price is what the customer actually paid per unit. It's the ground truth for demand response, which is what elasticity measures.
  - It does not depend on whether `coupon_disc` is already inside `sales_value`. That question is unresolved (Test B was ambiguous: 26 asis wins vs 35 added-back wins across 63 groups, with the two metrics disagreeing). The net formula sidesteps the ambiguity entirely.
  - Tools that take price as an input (elasticity, margin calculation, markdown recommendation) want the price the customer faced, not a reconstructed shelf price. 
   - The coupon-inside-or-separate question was deliberately left unresolved rather than forced. Test B produced genuinely ambiguous evidence (35 vs 26 win-count for "inside", 57%, not statistically distinguishable from chance; average-distance metric pointed the other way). Rather than guess, the design uses a formula that works under either hypothesis. Designing around an honest ambiguity beats a fabricated confirmation.
- **Trade-offs / what I'd revisit:**
  - Cannot directly compare "shelf price" across coupon and non-coupon rows. If a future tool needs that, Test B has to be redone with tighter methodology (per-group ratios, larger n).
  - `coupon_disc` and `coupon_match_disc` are still reported separately in summaries as rebates the customer received, so the information isn't lost — just not folded into the price.
  - If a future decision needs list price (for example, to compute a discount % off shelf), revisit D-003, don't override it silently. 
    - `retail_disc > 0` appears in 36 rows out of 2.6M (0.0014%). 30 are floating-point noise on return rows; 6 are real small positives on normal rows, unexplained. The tools clip `retail_disc` to `min(retail_disc, 0)` before use and log the clipped-row count in output metadata.
    
---

### D-004: Promo-week definition
- **Date:** 2026-09-22
- **Context:** Three downstream tools need a single answer to "was this product on promo this store this week?" The data offers three signals: a price discount (`retail_disc` in transactions), a display placement (`display` in causal), and a mailer placement (`mailer` in causal). Day 3 Test C showed that "has a causal row" is too loose (20% of all sold product-store-weeks, thousands of products flagged per store-week). A stricter rule is needed.
- **Options considered:**
  1. `retail_disc <> 0` in that week. Rejected: ~50% of rows have a discount. It flags half the data.
  2. Any nonzero `display` or `mailer`. Rejected: 20% coverage and a single store-week can flag thousands of products at once, consistent with a weekly circular rather than a targeted promotion.
  3. Discount depth (`1 - net_revenue / list_revenue`) above a threshold. Chosen.
- **Decision:** A product is on promo in a store-week iff its volume-weighted discount depth is **>= 0.35**. The `is_featured` flag (any causal row that week) is kept as a secondary signal, reported separately, not used as the primary promo definition.
- **Why:**
  - 0.35 flags 13.4% of all product-store-weeks, matching the target "promo is the exception, not the norm."
  - It sits close to the 75th percentile of the discounted-week distribution (p75 = 0.367). A clean round number just below that cutoff flags the top 26.9% of discounted weeks — clean and interview-friendly, and defensible from the data rather than pulled from air.
  - Discount depth is a continuous measure of price cut, which is what elasticity needs. A binary flag alone would throw away the depth information.
- **Trade-offs / what I'd revisit:**
  - **Confound with display.** At 0.35, 186,199 of 316,372 promo weeks (59%) also had a display or mailer. Diff-in-diff cannot separate the price effect from the display effect on those. The 130,173 clean weeks are the primary sample for Week 4. This is a named limitation, not a reason to change the threshold today.
  - The threshold is a design choice, not a data fact. If Week 2's elasticity estimates look too noisy or too sparse, revisit 0.30 or 0.25 to gain more weeks. Document the new value and the reason.
  - `is_featured` is coarse: any causal row counts, including display codes like "In-Shelf" that may not be a real promotion. Not used as the primary flag for that reason.
  
---

### D-005: Confidence rule and COUPON/MISC flag in get_sales_summary
- **Date:** 2026-09-22
- **Context:** `get_sales_summary` returns a summary number that callers may act on. Two failure modes make a number untrustworthy: (1) too little data to be meaningful, and (2) the product_id is a bookkeeping line that looks like a real product but isn't. Both need explicit handling, not silence.
- **Options considered:**
  1. Return a number with no confidence signal. Rejected: a caller can't tell whether to trust it.
  2. Return only a number, with a separate helper to compute confidence. Rejected: easy to forget.
  3. Return a confidence label plus explanatory notes on the same result. Chosen.
- **Decision:**
  - Confidence is "high" only when the window has at least 4 calendar weeks AND the product had sales in at least 4 distinct weeks. Otherwise, "low."
  - If the product's `commodity_desc` is `COUPON/MISC ITEMS`, append a warning note to the result.
- **Why:**
  - **Two checks, not one.** The original requirement said "fewer than 4 weeks of data," which is ambiguous. A 3-week request is thin even when all 3 weeks had sales. A 30-week request where the product only sold in 2 weeks is also thin. Both are "low confidence." Using only one check would miss the other case.
  - **Distinct weeks, not rows.** `product_store_week` is one row per product x store x week, so counting rows would count "100 stores sold it one week" as if it were 100 weeks of history. The confidence check counts distinct `week_no` values, which is calendar coverage.
  - **COUPON/MISC flag.** Day 3 Test A showed that three of the top products by revenue were `COUPON/MISC ITEMS` bookkeeping lines. A caller asking for a summary of one of those IDs would get a plausible-looking revenue number and no warning. The flag turns a silent misdirection into a visible note.
- **Trade-offs / what I'd revisit:**
  - 4 weeks is a heuristic, not a derived number. If Week 2's elasticity model needs a tighter or looser rule, revisit it, but keep it documented here rather than changing it silently.
  - "High confidence" does not mean the result is correct, only that there's enough data for a basic summary. It says nothing about causal claims, which need the diff-in-differences work in Week 4.
  - The confidence field is a string ("high" / "low") rather than a numeric score. Simple and readable, but hard to threshold. If a downstream tool needs graded confidence, add a numeric field alongside rather than replacing this one.

---

### D-006: get_sales_summary counted store-weeks as weeks; product_week added
- **Date:** 2026-10-02
- **Context:** `get_sales_summary` returned `n_weeks_with_sales`, `n_promo_weeks`, and `n_featured_weeks`. These were computed as `COUNT(*)` and `SUM(is_price_promo::INT)` over `product_store_week`, which is one row per product x store x week. The field names claimed "weeks." The values were store-week counts. For any product sold in more than one store, the number was inflated by roughly the store count.
- **Options considered:**
  1. Rename the fields to match what they actually counted (store-weeks). Rejected: callers want calendar-week counts, not store-week counts.
  2. Compute `COUNT(DISTINCT week_no)` on `product_store_week` for the summary, and leave the table alone. Rejected: the same trap stays available for the next caller.
  3. Build a `product_week` table (one row per product per week, aggregated across stores) and read summaries from that. Chosen.
- **Decision:** Add `product_week` to `retail_memory.data.promo`, and change `get_sales_summary` to read from it. Rename the affected fields to `n_distinct_weeks_with_sales`, `n_distinct_promo_weeks`, `n_distinct_featured_weeks`. `product_store_week` remains the store-level table for Week 4 cannibalization.
- **Why:**
  - `COUNT(*)` over `product_store_week` silently counts store-weeks. Nothing in the code or the field name says so. A field named `n_weeks_with_sales` invites exactly this mistake.
  - Having a dedicated `product_week` table makes the "true week count" the default for summaries, and the store-level table becomes a deliberate choice (for diff-in-diff work), not the accidental default.
  - Renaming the fields closes the trap: `n_distinct_weeks_*` cannot be misread as anything but distinct calendar weeks.
- **Measured impact of the bug (anchor product 1029743, fluid milk):**
  - Buggy: 62 (`SUM(is_price_promo::INT)` over `product_store_week`)
  - Fixed: 6 (same sum over `product_week`)
  - Stores that ever sold it: 115
  - Distinct weeks with any store promoting: 6 (weeks 5, 11, 18, 23, 29, 57)
  - Inflation factor: ~10x. Small number of promo weeks; each was promoted across many stores at once, so the store-week count looked much larger.
- **A second bug caught during the fix:** the first version of `product_week` recomputed `discount_depth` at the aggregate grain and re-applied the threshold. For the anchor product this produced **0** promo weeks, because the volume-weighted average across all 115 stores fell below 0.35 (max store depth in those weeks was 0.38-0.44, aggregate was 0.26-0.34). The threshold was calibrated at the store grain. Re-applying it at a coarser grain diluted the signal.
- **Correct definition, now in code:** `product_week.is_price_promo` is `MAX(is_price_promo)` over the stores selling that product that week. "On promo this week" means "on promo in any store this week." Same for `is_featured`. This preserves the store-level threshold and matches how a manager would answer the question.
- **Trade-offs / what I'd revisit:**
  - `product_week.discount_depth` is still the volume-weighted aggregate across stores, kept for reference. It is NOT the value used for the promo flag. A reader who does not know this could re-apply the threshold and get the wrong answer again. The column docstring calls this out.
  - `product_week.is_featured` uses `MAX` across stores, so "featured" means "any store featured it." This is a looser definition than store-level featuring, and it matters if Week 4 wants store-specific treatment. For summaries it is the right grain; for causal work, read from `product_store_week`.
- **Addendum (2026-10-02): flag rename and bound test.**
  - The `product_week` flag originally named `is_price_promo` was renamed to
    `is_price_promo_any_store`. Reason: at product-week grain, the flag means
    "at least one store cleared the threshold," but the column sat next to
    `discount_depth`, which is the volume-weighted average across all stores.
    Two different quantities, similar names, easy to conflate. A week with 5 of
    40 stores promoting gets flagged True while the aggregate depth sits around
    0.15 -- the flag and the depth disagree by construction, not by bug.
  - **Authoritative sources:**
    - `product_week.is_price_promo_any_store` -- for screening candidate
      products only (Day 6 elasticity work). Loose definition: any-store.
    - `product_store_week.is_price_promo` -- the per-store-week flag, the
      primary definition for Week 4 cannibalization (D-004). Authoritative.
  - **Bound test added** (`test_any_store_flag_bound_holds` in
    `tests/test_real_data.py`): every row flagged False must have aggregate
    discount_depth < 0.35, because a weighted average cannot exceed its largest
    input. `max_depth_when_not = 0.3499` confirms this empirically. The test
    locks the property in so any future drift is caught by CI.
    
---

### D-009: estimate_elasticity as a separate function from recommend_markdown
- **Date:** 2026-10-09
- **Context:** The project needs both a "what does the data say" estimator and a
  "what should we do" recommender. These could be combined into one function.
- **Decision:** Keep them separate. `estimate_elasticity` returns an estimate or a
  refusal, with method, CI, and confidence. `recommend_markdown` will take that
  estimate and add margin economics on top, as a distinct function in a distinct
  module.
- **Why:**
  - Different inputs. `estimate_elasticity` only needs a product_id. `recommend_markdown`
    needs a margin assumption, which is separate economic input the data can't supply.
  - Different callers. The agent will route to `estimate_elasticity` for "how elastic
    is X" and `recommend_markdown` for "what discount should I run on X." A combined
    function would still need branchy output.
  - Testability. The estimator is testable against the notebook's hand fits; the
    recommender's margin math is a separate concern with its own tests.
  - Interview clarity. "I separated estimation from decision" is a cleaner design
    story than "one function does both."
- **Branch selection inside estimate_elasticity.** The function has three branches:
  - **refused** if quantity is degenerate (D-008) or weeks < 20
  - **month_fallback** if pricing is centralized (avg within-week price SD < 0.01)
  - **two_way_fe** otherwise (week + store FE, store-clustered SEs)
- **Verification against notebook hand-fits:**
  - 995242: −0.226, CI [−0.466, 0.015] — matches
  - 1133018: −0.162, CI [−0.426, 0.103] — matches
  - 201704 (banana): refused on degenerate quantity — matches D-008
- **Trade-offs / what I'd revisit:**
  - Two functions means two places to keep aligned if estimation logic changes.
  - Refusal logic lives only in the estimator; the recommender must propagate
    refusals, not re-implement them.
  - Confidence is currently binary ("high" if CI excludes zero, "low" otherwise).
    A numeric score would be more expressive but harder to threshold. Revisit
    if a downstream tool needs gradations.
    
---

### D-010: recommend_markdown pricing formula and refusal logic
- **Date:** 2026-10-09
- **Context:** Given an elasticity estimate and an assumed margin, recommend a discount
  depth that maximizes predicted profit, or refuse to recommend.
- **The economics.** Under constant-elasticity demand, the profit-maximizing margin is
  `1/|e|` (the Lerner inverse). Two cases:
  - If `|e| <= 1` (inelastic), no finite discount improves profit. Refuse with
    `no_discount_indicated`.
  - If `|e| > 1` (elastic), compute `optimal_margin = 1/|e|`. If the current margin
    is already at or below that, the product is priced favorably; no discount indicated.
    If the current margin exceeds it, the product is overpriced relative to what
    elasticity supports, and the recommended price is `cost / (1 - optimal_margin)`.
- **Decision:** Implement this formula in `recommend_markdown`, with three refusals:
  1. If `estimate_elasticity` refused (`method == "refused"`).
  2. If `confidence == "low"` (CI includes zero, can't confirm price matters at all).
  3. If `margin` is out of (0, 1).
- **Why:** A tool that can't tell whether price affects demand has no business
  computing a confident markdown number. The `confidence == "low"` refusal is what
  keeps the tool honest; it isn't a data-sparsity refusal, it's a "the answer might
  be zero and we can't rule it out" refusal.
- **Clip rule.** The recommended discount is clipped to the deepest discount ever
  observed for that product (`_historical_max_discount_depth`). Follows the D-008
  principle: never recommend outside the observed data range.
- **Profit change calculation.** Profit at price P relative to baseline P0 under
  constant elasticity is `[(P - C) / (P0 - C)] * (P / P0)^e`. Point estimate uses the
  coefficient; the range uses `ci_low` and `ci_high` for a plausible band.
- **Verification:**
  - Real products 995242 and 1133018 both `insufficient_data` (low confidence CI
    includes zero). Correct: the tool refuses to recommend a discount for a staple
    where the price effect isn't statistically distinguishable from zero.
  - Six synthetic tests cover: inelastic -> no discount; margin below optimal -> no
    discount; margin above optimal -> recommended; deep discount -> clipped to historical.
    - **Real-product outcomes (all four refuse):** 995242 and 1133018 both refuse on
    low confidence (CI includes zero). 201704 refuses on degenerate quantity (D-008
    propagation). 1113588 (month_fallback branch) refuses on low confidence with a
    very wide CI [-6.672, 1.321]. No real product examined so far supports a
    confident markdown recommendation. This is the correct, honest output, not a
    bug: no product in the current sample has a CI that excludes zero, so the tool
    has nothing to recommend against.
- **Trade-offs / what I'd revisit:**
  - The `margin` input is assumed, not measured. Real cost data isn't in this dataset.
  - The formula assumes constant elasticity, ignores competitor response and
    cross-product effects.
  - Recommendation uses `|e|` point estimate; CI feeds only the profit range, not the
    refuse/accept gate. A stricter version would refuse when the CI is wider than some
    threshold.
    
---

### D-011: Three-way confidence taxonomy and elasticity guardrails
- **Date:** 2026-10-10
- **Context:** Ran `estimate_elasticity` on the 30 highest-volume candidates from the
  Day 6 screen, using the post-hardening version of the function. Result: 22 low
  confidence, 3 insufficient_data, 5 high confidence. Total 30. Of the 5 high
  confidence, **zero** would produce a `recommend_markdown` "recommended" result,
  because all 5 have |e| < 1 (inelastic). This confirms the revisit trigger named in
  D-001 before any modeling was done.
- **The three-way taxonomy (headline framing):**
  1. **Low confidence (22):** "we can't tell if price matters." CI includes zero or
     sits inside the ±0.05 practical-significance band.
  2. **Insufficient data (3):** refused by a guardrail — degenerate quantity,
     singular matrix, positive coefficient, or too few weeks.
  3. **High confidence but inelastic (5):** "price matters, but not enough to make
     discounting profitable." |e| < 1. Correct answer is no discount. Products:
     1127831 (e=−0.709), 1029743 (e=−0.387), 1058997 (e=−0.329),
     923746 (e=−0.308), 916122 (e=−0.203).
  4. **High confidence and elastic (0):** "discount is justified." None in the sample.
- **Decision: ship `recommend_markdown` as built.** Refusing honestly on low power
  and on inelastic demand is correct behavior, not a bug. It matches the project's
  never-overclaim design. Sub-commodity or department-level pooling (the fix D-001
  anticipated) is deferred: priority is reaching the Week 3 agent, and the current
  per-product tool produces honest answers on a real sample.

**Guardrails added during the batch scan:**

- **Singular matrix detection.** Real fit on product 1007195 fired a
  `SingularMatrixWarning` (rank-deficient design matrix from sparse store/week
  combinations). Fixed with a `_fit_checked` helper that catches the warning and
  returns `"refused"` rather than reporting a coefficient from a broken fit. Applied
  to both `two_way_fe` and `month_fallback` branches.

- **Positive coefficient refusal.** Product 995785 returned +0.650 (CI [0.244, 1.056]).
  Diagnosed the mechanism: quantity varies normally (not a banana case) and
  `curr_size_of_product = "48-54 CT"`. Root cause is most likely **price
  endogeneity**: seasonal demand peaks push prices up (supply-constrained), so
  price and quantity move together. Not the D-008 measurement failure, but the
  practical remedy is the same — refuse. Positive, statistically significant
  coefficients are not plausible normal-good demand.

- **Practical-significance epsilon.** Product 844179 had CI [−0.184, −0.001], and
  1126899 had [−0.708, −0.027]. Both technically exclude zero, but their CIs sit
  inside the ±0.05 practical-significance band. Neither should count as "high"
  confidence. Added `PRACTICAL_SIGNIFICANCE_EPSILON = 0.05`; a CI must clear this
  band on one side to earn "high" confidence.

**Verification (real data):**
- 1007195 — singular matrix, now refused.
- 995785 — positive coefficient, now refused.
- 844179, 1126899 — demoted from high to low by the epsilon rule.
- Best surviving high-confidence case: **1127831**, e = −0.709, CI [−0.834, −0.584].
  Inelastic, so `recommend_markdown` returns `no_discount_indicated`. Clean demo case
  for Week 3.
- Clean low-confidence contrast case: **995242**, milk, CI includes zero.

**Trade-offs / what I'd revisit:**
- `PRACTICAL_SIGNIFICANCE_EPSILON = 0.05` is a judgment call, not derived. Chosen
  because in grocery retail a price elasticity of |e| < 0.05 is effectively zero
  from a pricing standpoint.
- Singular-matrix handling refuses the product entirely; a better long-term fix
  would be to drop the problematic store/store-week cells and refit.
- Positive coefficient refusal catches both measurement failure (D-008) and
  endogeneity (D-011). The `notes` field distinguishes the two cases when known,
  but the refusal is identical.
- The taxonomic finding — three categories of products, not one — is a stronger
  interview story than a single binary "works / doesn't work" claim.
  
---

### D-012: Rule-based router limitations (why an LLM is needed)
- **Date:** 2026-10-10
- **Context:** Before building the Groq tool-calling agent (Day 13+), built the
  simplest possible alternative: a plain Python function that routes a question to
  a tool by keyword matching. Purpose is twofold: (1) make the value of real
  tool-calling visible by contrast, (2) provide a zero-dependency fallback that
  needs no API key or network (NFR7).
- **Decision:** Ship `src/retail_memory/agent/router.py` as an explicitly imperfect
  baseline. Tests deliberately include failing cases as documentation of the
  router's limits.
- **Observed failures (from the test suite):**
  - **No keywords at all.** "Is product X doing well?" contains none of "summary",
    "sales", "revenue", "discount", "markdown", "margin". Routes to `UNKNOWN`. A
    human reads this as a sales-performance question; the router can't.
  - **Ambiguous overlap.** "How much revenue would a markdown on product X bring
    in?" matches BOTH keyword groups. The router returns `SALES_SUMMARY` because
    the "revenue" check happens first in the `if` chain. The user's actual intent
    is a markdown recommendation, so the router is confidently wrong -- and the
    wrongness comes from dictating check order, not from any semantic understanding.
- **What an LLM does differently.** A tool-calling LLM parses the *subject* of a
  question (what is being asked about: revenue, markdown, cannibalization) rather
  than scanning for the first matching token. It also handles paraphrase:
  "will discounting hurt us" and "should we cut the price" both route to the
  markdown tool without needing a keyword list. The rule-based version needs a
  keyword for each phrasing, and the list grows unboundedly.
- **Why ship it anyway:**
  - It is testable, deterministic, and always available (no API key, no network).
  - It gives the Week 3 agent a fallback path if Groq is unreachable (NFR8).
  - It makes the interview answer concrete: "here's the exact question that
    breaks keyword matching, and here's what the LLM does instead."
- **Trade-offs / what I'd revisit:**
  - The keyword lists are small and will miss common phrasings. This is intentional:
    the router is not meant to be improved, it's meant to be a floor.
  - No confidence score. Every match is treated as equally certain, including
    the ambiguous-overlap case where the router is likely wrong.
  - Not integrated into the agent yet. Day 13 wires the agent to prefer the LLM
    router and fall back to this one on API failure.
    
---

### D-013: First Groq tool call -- router comparison and a new failure mode
- **Date:** 2026-10-10
- **Context:** Day 13 wires Groq's tool-calling API to `get_sales_summary` via a Pydantic schema. The point is direct comparison against the rule-based router (D-012) on the same questions.
- **Model note:** Got a **404** on `llama-3.1-8b-instant` and a **tool_use_failed** error on `llama-3.3-70b-versatile` as of 2026-10-10. Groq's docs (console.groq.com/docs/tool-use) list both as tool-use-capable, so the 404 is more likely a stale or renamed model ID than a capability gap; the two errors are different failure types and shouldn't be collapsed. Switched to `openai/gpt-oss-120b`, which is independently confirmed as tool-use-capable and works end-to-end here.
- **Results on three questions:**

  | Question | Router | Groq |
  |---|---|---|
  | "total sales for 995242, weeks 1-20" | SALES_SUMMARY | SALES_SUMMARY, args {product_id:995242, start_week:1, end_week:20} |
  | "Is product 995242 doing well?" | UNKNOWN | SALES_SUMMARY, args {product_id:995242, start_week:90, end_week:102} |
  | "revenue from a markdown on product X" | SALES_SUMMARY (wrong) | no tool call; asked for product ID, week range, discount details |

- **The router's two documented failures are both addressed.** Q2 (no-keyword) routes correctly via intent recognition. Q3 (ambiguous overlap) is handled by asking for clarification instead of guessing.
- **New failure mode discovered.** On Q2, Groq invented a 13-week window (weeks 90-102) for "doing well" without asking. The answer would look authoritative but the parameters weren't the user's. Where the router fails loudly (UNKNOWN), the LLM fails quietly (confident answer, invented args).
- **Design implication.** The agent layer (Day 14+) must add a confirmation step for underspecified questions -- either asking the user for the window, or stating "assuming last 13 weeks" before executing. Confidently-wrong is worse than visibly-broken.
- **Trade-offs / what I'd revisit:**
  - The Q2 behavior is defensible as a UX choice if the agent *tells* the user what it assumed. Silent assumptions are the problem.
  - Only one tool is available today. Q3's real test (sales vs markdown routing) requires Day 14's second tool.

---

### D-014: System prompt v1 -- rules, comparison table, and where it fails
- **Date:** 2026-10-10
- **Context:** Day 13 found that Groq silently invented parameters on underspecified questions (q2: "Is product 995242 doing well?" → called with weeks 90-102, no mention). System prompt v1 (src/retail_memory/agent/prompts.py) was written to address this, with four rules.
- **System prompt v1 rules:**
  1. Always call a tool to get numbers; never state a figure yourself.
  2. If no tool matches, say so rather than answering from general knowledge.
  3. If a required parameter is missing, either ask for clarification, or state the assumption explicitly in the reply. Never silently assume.
  4. Never invent a product ID.
- **Five-question comparison (router vs. Groq):**

  | Q | Question | Router | Groq | Outcome |
  |---|---|---|---|---|
  | q1 | "total sales 995242, weeks 1-20" | SALES_SUMMARY | `get_sales_summary({995242, 1, 20})` | correct |
  | q2 | "Is product 995242 doing well?" | UNKNOWN | `get_sales_summary({995242, 90, 102})` | **silent assumption** |
  | q3 | "revenue from markdown on product X" | SALES_SUMMARY (wrong) | declined, asked for ID + margin | correct |
  | q4 | "weather today?" | UNKNOWN | "I can't answer that with the available tools." | correct |
  | q5 | "Should I discount product X?" | MARKDOWN | declined, asked for ID + margin | correct |

- **The key finding: rule 3 did not work on q2.**
  - Where rules 2 and 4 succeeded (q4 and q5 both followed them), the one rule requiring an explicit statement *before* a tool call failed.
  - Structural cause: the tool-call path in the Groq/OpenAI API produces `tool_calls` as a separate field. When the model decides to call a tool, it doesn't emit a `content` reply. There is no opportunity to say "assuming the most recent 13 weeks" because the only output is the arguments.
  - This is not a prompt-writing weakness. It's an API-shape constraint. Any system prompt that says "state your assumption before calling" is unenforceable through the tool-call path alone.

- **Resolution paths for Day 15+ (agent loop):**
  1. **Intercept and re-present.** The agent layer inspects tool calls before executing, and if a required parameter was not in the user's original question, it returns a clarification turn instead of executing. This requires the agent loop to distinguish "parameter was in the question" from "parameter was invented."
  2. **Add a required `reasoning` parameter to each tool schema.** The model must produce text explaining the choice in the same payload as the args. Increases payload size but makes assumptions visible.
  3. **Two-turn pattern.** First turn: model must produce a text reply that summarises its understanding. Second turn: execute. Doubles latency.

  Option 1 is the cleanest. It's also where the design was already heading (the agent owns the loop, not the model).

- **q3 resolved.** With `recommend_markdown` available, the D-012 ambiguous-overlap case is fixed: Groq declines and asks for clarification rather than confidently routing to sales. The router's failure (SALES_SUMMARY) is now demonstrably worse than the LLM's response.

- **Trade-offs / what I'd revisit:**
  - Prompt v1 is a live experiment, not a final version. Expect to iterate v2 after the agent loop is built (Day 15) and the re-presentation layer exists.
  - No numeric eval score yet. Day 19 builds the eval harness that will turn this table into a pass rate.
  - q4 was easy. A harder out-of-scope question ("what's the best price for competitor product Y?") would test rule 2 more stringently.
  
---

### D-015: Agent loop -- real tool execution with code-side interception
- **Date:** 2026-10-10
- **Context:** Day 14 showed the prompt cannot prevent the model from silently inventing parameters (rule 3 did not fix q2). Day 15 builds the agent loop that does the validation in code, not in the prompt.
- **Loop structure:**
  1. Send question + SYSTEM_PROMPT_V1 + both tool schemas to Groq.
  2. If no tool call → return "declined" with the model's text.
  3. If tool call → extract args, check each value against the question text via `_value_appears_in_text`.
  4. If any parameter value doesn't appear in the question → return "clarification_needed" with a plain-language ask.
  5. If all parameters trace to the question → execute the real tool, serialize the dataclass with `asdict` + `json.dumps`, send the result back to Groq as a `tool` role message.
  6. Groq explains the result in plain language; return as "answered".
- **Why code-side, not prompt-side:** Day 14 tested the prompt-based approach and it failed structurally. The model produced a tool call with no accompanying content, so a "state your assumption" rule had nothing to attach to. Code-side validation is authoritative regardless of what the model says.
- **Known limitation (documented as revisit trigger in D-014):** `_value_appears_in_text` is a literal substring check. It catches pure invention but not legitimate inference presented as fact. A `assumption_note` schema field would close that gap; deferred.
- **Three real test results (2026-10-10):**
  - **Q1 (clean):** "total sales 995242, weeks 1-20" → `answered`. Tool called: `get_sales_summary(995242, 1, 20)`. Final text: "Total units sold: 2,235, Total revenue: $2,694.32." Verified against raw tool output — matches.
  - **Q2 (invented params):** "Is product 995242 doing well?" → `clarification_needed`. Invented: `['start_week', 'end_week']`. Interception worked — no tool executed.
  - **Q3 (real round trip):** "Should I discount product 1127831 assuming a 30% margin?" → `answered`. Tool called: `recommend_markdown(1127831, 0.30)`. Final text reported e=−0.709, CI [−0.834, −0.584], current price $3.91, no discount, with the inelastic note. **Verified against raw MarkdownRecommendation output — no editorialising, no rounding beyond the tool's own values, no invented numbers.**
- **Small bug found and fixed during the run:** the clarification message originally leaked internal parameter names (`end_week, start_week`). Added a `PARAM_LABELS` map so the user sees "the starting week and the ending week".
- **Trade-offs / what I'd revisit:**
  - One tool call per turn. If the model ever wants to chain tools (sales summary → recommend markdown), the loop must be extended.
  - No iteration limit on the follow-up turn. If Groq loops on a follow-up, this hangs. Day 16's guardrails should add a max-turns cap.
  - The `_value_appears_in_text` check is over-conservative by design (see D-014 revisit trigger).