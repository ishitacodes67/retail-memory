# Data notes

## Files, sizes and columns
| File | Rows | Columns | One row is... |
|------|------|---------|---------------|
| transaction_data.csv | 2,595,732 | household_key, BASKET_ID, DAY, PRODUCT_ID, QUANTITY, SALES_VALUE, STORE_ID, RETAIL_DISC, TRANS_TIME, WEEK_NO, COUPON_DISC, COUPON_MATCH_DISC | one product line in a basket, at one store, on one day |
| causal_data.csv | 36,786,524 | PRODUCT_ID, STORE_ID, WEEK_NO, display, mailer | one product x store x week, with marketing flags |
| product.csv | 92,353 | PRODUCT_ID, MANUFACTURER, DEPARTMENT, BRAND, COMMODITY_DESC, SUB_COMMODITY_DESC, CURR_SIZE_OF_PRODUCT | one product |
| hh_demographic.csv | 801 | AGE_DESC, MARITAL_STATUS_CODE, INCOME_DESC, HOMEOWNER_DESC, HH_COMP_DESC, HOUSEHOLD_SIZE_DESC, KID_CATEGORY_DESC, household_key | one household |
| campaign_desc.csv | 30 | DESCRIPTION, CAMPAIGN, START_DAY, END_DAY | one campaign |
| campaign_table.csv | 7,208 | DESCRIPTION, household_key, CAMPAIGN | one household in one campaign |
| coupon.csv | 124,548 | COUPON_UPC, PRODUCT_ID, CAMPAIGN | one coupon UPC x product x campaign |
| coupon_redempt.csv | 2,318 | household_key, DAY, COUPON_UPC, CAMPAIGN | one coupon redemption event |

## Q1. What is one row of transaction_data?

SQL used:

```sql
SELECT * FROM txn LIMIT 5;
SELECT basket_id, COUNT(*) FROM txn GROUP BY basket_id ORDER BY 2 DESC LIMIT 5;
```

Result:

- First 5 rows all share household 2375 and basket 26984851472
- Top baskets have 150-168 rows each

My answer: One row is one product line item (one item, quantity, and price) inside one shopping basket, which belongs to one household, on one day, at one store.

## Q2. How many weeks and days?

SQL used:

```sql
SELECT MIN(week_no), MAX(week_no), COUNT(DISTINCT week_no), MIN(day), MAX(day) FROM txn;
```

Result:

- week_no: 1 to 102
- distinct weeks: 102
- day: 1 to 711

My answer: The data covers 102 weeks (about 2 years). 711 days / 7 = 101.6, which matches the 102 distinct weeks. Every week appears; no gaps.

## Q3. How many products, stores and households?

SQL used:

```sql
SELECT COUNT(DISTINCT product_id), COUNT(DISTINCT store_id), COUNT(DISTINCT household_key) FROM txn;
SELECT COUNT(DISTINCT t.product_id) FROM txn t LEFT JOIN product p ON t.product_id = p.product_id WHERE p.product_id IS NULL;
```

Result:

- distinct products: 92,339
- distinct stores: 582
- distinct households: 2,500
- products sold but missing from product.csv: 0

My answer: 92,339 products, 582 stores, 2,500 households. Every product sold has metadata in product.csv (referential integrity holds). 2,500 households is a small slice of shoppers, so per-product weekly volumes will be sparse and I'll need to focus on high-volume products.

## Q4. What do the three discount columns mean?

SQL used:

```sql
SELECT MIN(retail_disc), MAX(retail_disc), MIN(coupon_disc), MAX(coupon_disc), MIN(coupon_match_disc), MAX(coupon_match_disc) FROM txn;
SELECT MAX(coupon_disc) FROM txn;
SELECT product_id, quantity, sales_value, retail_disc, coupon_disc, coupon_match_disc FROM txn WHERE retail_disc <> 0 LIMIT 10;
SELECT quantity, sales_value, retail_disc, coupon_disc, coupon_match_disc FROM txn WHERE coupon_disc <> 0 LIMIT 10;
```

Result:

- retail_disc: min -180.00, max +3.99 (almost always zero or negative)
- coupon_disc: min -55.93, max 0.00
- coupon_match_disc: min -7.70, max 0.00
- Rows where coupon_disc <> 0 include cases with retail_disc = 0 (e.g. qty 2, sales_value 3.78, retail_disc 0, coupon_disc -1.0). So the two discounts are separate, not nested.

My answer (hypothesis, to test on Day 3): All three discount columns are almost always zero or negative, so a discount reduces the price. A few positive retail_disc values exist (max +3.99); investigate on Day 3.

Tentative formula (hypothesis, not verified):

```
gross_value    = sales_value - retail_disc - coupon_disc - coupon_match_disc
net_value      = sales_value
net_unit_price = net_value / quantity
```

Because discounts are negative, subtracting them from sales_value reconstructs the pre-discount gross. KEY UNKNOWN: whether coupon_disc is already inside sales_value. If it is, the formula double-counts. Test on Day 3 against known coupon redemptions.

## Q5. What is causal_data?

SQL used:

```sql
SELECT * FROM causal LIMIT 10;
SELECT display, COUNT(*) FROM causal GROUP BY display ORDER BY 2 DESC;
SELECT mailer, COUNT(*) FROM causal GROUP BY mailer ORDER BY 2 DESC;
SELECT (display = '0') AS no_display, (mailer = '0') AS no_mailer, COUNT(*) FROM causal GROUP BY 1, 2 ORDER BY 3 DESC;
```

Result:

- Grain: product_id x store_id x week_no
- display values: 0, 1, 2, 3, 4, 5, 6, 7, 9, A
- mailer values: 0, A, C, D, F, H, J, L, P, X, Z
- Cross-tab:
  - no display, has mailer: 21,038,745 rows (57.2%)
  - has display, no mailer: 11,534,183 rows (31.4%)
  - has display, has mailer: 4,213,596 rows (11.5%)
  - no display, no mailer: 0 rows (0.0%)

My answer: One row is one product, in one store, in one week, with a display flag and a mailer flag.

Code meanings (from the `completejourney` R package documentation, which wraps this dataset):

Display location codes:

| Code | Meaning |
|------|---------|
| 0 | Not on Display |
| 1 | Store Front |
| 2 | Store Rear |
| 3 | Front End Cap |
| 4 | Mid-Aisle End Cap |
| 5 | Rear End Cap |
| 6 | Side-Aisle End Cap |
| 7 | In-Aisle |
| 9 | Secondary Location Display |
| A | In-Shelf |

Mailer location codes:

| Code | Meaning |
|------|---------|
| 0 | Not on ad |
| A | Interior page feature |
| C | Interior page line item |
| D | Front page feature |
| F | Back page feature |
| H | Wrap from feature |
| J | Wrap interior coupon |
| L | Wrap back feature |
| P | Interior page coupon |
| X | Free on interior page |
| Z | Free on front page, back page or wrap |

Key observation: every row in causal_data has at least one nonzero flag (0 rows with both display = '0' and mailer = '0'). Most likely this is because the table only lists product-store-weeks where something was featured; a product with no display and no flyer that week simply has no row. Hypothesis: "no row" = "not featured". Test on Day 3 by joining transactions to causal_data on product, store and week.

Note on the name: "causal" here means "marketing treatments". Nobody randomly assigned which products got flyers or displays. That makes this observational data, not experimental. Any causal claim needs a proper design (diff-in-diff, control product, baseline), which is why Week 4 builds the naive-then-fixed story.

## Q6. Strange rows (zero or negative)?

SQL used:

```sql
SELECT COUNT(*) FROM txn WHERE quantity <= 0;
SELECT COUNT(*) FROM txn WHERE sales_value <= 0;
SELECT * FROM product WHERE product_id IN (5978648, 5978656);
SELECT (quantity <= 0) AS qty_le0, (sales_value <= 0) AS val_le0, COUNT(*) FROM txn GROUP BY 1, 2 ORDER BY 3 DESC;
```

Result:

- quantity <= 0: 14,466 rows (0.56% of total)
- sales_value <= 0: 18,850 rows (0.73%)
- Overlap:
  - normal (qty>0, val>0): 2,576,815 rows
  - both bad (qty<=0, val<=0): 14,399 rows, most likely returns or voided items
  - val bad only (qty>0, val<=0): 4,451 rows, possibly free items
  - qty bad only (qty<=0, val>0): 67 rows, very strange
- Products 5978648 and 5978656 exist in product.csv with MANUFACTURER=1, BRAND='National', and every other field blank

My answer: The 14,399 rows with both quantity<=0 and sales_value<=0 are most likely returns or voided items. The 4,451 rows with positive quantity but zero/negative sales_value are likely free items or data errors; flag on Day 3. The 67 rows with negative quantity but positive sales_value are strange; also flag.

Two product IDs (5978648, 5978656) have minimal metadata in product.csv, consistent with coupon line items. I only checked those two, so I won't generalize to "everything above 5,000,000 is a coupon" without more evidence.

Open decision: for revenue summaries, report gross (all rows) or net (returns subtracted)? For elasticity and cannibalization, exclude returns and free items.

## Open questions

- What counts as a "promo" for a product-week? Candidates: (a) a price cut, measured from retail_disc in transaction_data; (b) being featured, i.e. a row in causal_data and which display/mailer codes matter; (c) both. Decide on Day 4.

- Does a missing causal_data row mean "not featured"? Test on Day 3.

- Is coupon_disc already deducted inside sales_value? If not, my gross-price formula double-counts the coupon. Test on Day 3.

- Why does retail_disc have a few positive values (max +3.99)? Investigate on Day 3.

- What are the 4,451 rows with qty>0 and val<=0, and the 67 rows with qty<=0 and val>0?

- For revenue summaries: gross (all rows) or net (returns subtracted)?