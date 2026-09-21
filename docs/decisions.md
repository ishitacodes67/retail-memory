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