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