# Data notes

## Files, sizes and columns
| File | Rows | Columns | One row is... |
|------|------|---------|---------------|
| transaction_data.csv | 2,595,732 | household_key, BASKET_ID, DAY, PRODUCT_ID, QUANTITY, SALES_VALUE, STORE_ID, RETAIL_DISC, TRANS_TIME, WEEK_NO, COUPON_DISC, COUPON_MATCH_DISC | |
| causal_data.csv | 36,786,524 | PRODUCT_ID, STORE_ID, WEEK_NO, display, mailer | |
| product.csv | 92,353 | PRODUCT_ID, MANUFACTURER, DEPARTMENT, BRAND, COMMODITY_DESC, SUB_COMMODITY_DESC, CURR_SIZE_OF_PRODUCT | |
| hh_demographic.csv | 801 | AGE_DESC, MARITAL_STATUS_CODE, INCOME_DESC, HOMEOWNER_DESC, HH_COMP_DESC, HOUSEHOLD_SIZE_DESC, KID_CATEGORY_DESC, household_key | |
| campaign_desc.csv | 30 | DESCRIPTION, CAMPAIGN, START_DAY, END_DAY | |
| campaign_table.csv | 7,208 | DESCRIPTION, household_key, CAMPAIGN | |
| coupon.csv | 124,548 | COUPON_UPC, PRODUCT_ID, CAMPAIGN | |
| coupon_redempt.csv | 2,318 | household_key, DAY, COUPON_UPC, CAMPAIGN | |


## Q1. What is one row of transaction_data?
SQL used:
SELECT * FROM txn LIMIT 5;
SELECT basket_id, COUNT(*) FROM txn GROUP BY basket_id ORDER BY 2 DESC LIMIT 5;

Result:
- First 5 rows all share household 2375 and basket 26984851472
- Top baskets have 150–168 rows each

My answer: One row is one product line item (one item, quantity, and price) inside one shopping basket, which belongs to one household, on one day, at one store.

## Q2. How many weeks and days?
SQL used:
SELECT MIN(week_no), MAX(week_no), COUNT(DISTINCT week_no), MIN(day), MAX(day) FROM txn;

Result:
- week_no: 1 to 102
- distinct weeks: 102
- day: 1 to 711

My answer: The data covers 102 weeks (about 2 years). 711 days ÷ 7 = 101.6, which matches the 102 distinct weeks. Every week appears; no gaps.

## Q3. How many products, stores and households?
SQL used:
SELECT COUNT(DISTINCT product_id), COUNT(DISTINCT store_id), COUNT(DISTINCT household_key) FROM txn;
SELECT COUNT(DISTINCT t.product_id) FROM txn t LEFT JOIN product p ON t.product_id = p.product_id WHERE p.product_id IS NULL;

Result:
- distinct products: 92,339
- distinct stores: 582
- distinct households: 2,500
- products sold but missing from product.csv: 0

My answer: 92,339 products, 582 stores, 2,500 households. Every product sold has metadata in product.csv (referential integrity holds). 2,500 households is a small slice of shoppers — per-product weekly volumes will be sparse, so I'll need to focus on high-volume products.

## Q4. What do the three discount columns mean?
SQL used:
SELECT MIN(retail_disc), MAX(retail_disc), MIN(coupon_disc), MAX(coupon_disc), MIN(coupon_match_disc), MAX(coupon_match_disc) FROM txn;
SELECT product_id, quantity, sales_value, retail_disc, coupon_disc, coupon_match_disc FROM txn WHERE retail_disc <> 0 LIMIT 10;

Result:
- retail_disc: min -180.00, max 3.99 (mostly negative)
- coupon_disc: min -55.93
- coupon_match_disc: min -7.70, max 0.00

My answer (hypothesis, to test on Day 3): All three discount columns are negative or zero — a discount reduces the price. sales_value appears to be the ALREADY-DISCOUNTED amount the customer paid. Example: product 1004906, quantity 1, sales_value 1.39, retail_disc -0.60 → gross was 1.99, a 30% discount. So:
    gross_unit_price = (sales_value - retail_disc - coupon_disc - coupon_match_disc) / quantity
    net_unit_price   = sales_value / quantity
Note: one outlier retail_disc = +3.99 exists. Investigate on Day 3.

## Q5. What is causal_data?
SQL used:
SELECT * FROM causal LIMIT 10;
SELECT display, COUNT(*) FROM causal GROUP BY display ORDER BY 2 DESC;
SELECT mailer, COUNT(*) FROM causal GROUP BY mailer ORDER BY 2 DESC;

Result:
- Grain: product_id × store_id × week_no
- display values: 0 (21M), 9, 5, 7, 3, 6, 2, 1, A, 4
- mailer values: A (17.1M), 0 (11.5M), D, H, F, J, L, C, X, Z, P

My answer: One row is one product, in one store, in one week, with a display flag and a mailer flag. `0` means no display / no mailer. Non-zero codes indicate a specific type of display or mailer. Per Kaggle docs, these are causally linked marketing treatments — that's why the table is named "causal." The exact meaning of each code (e.g. mailer 'A' vs 'D') is documented on Kaggle; don't guess.

## Q6. Strange rows (zero or negative)?
SQL used:
SELECT COUNT(*) FROM txn WHERE quantity <= 0;
SELECT COUNT(*) FROM txn WHERE sales_value <= 0;
SELECT * FROM txn WHERE sales_value <= 0 LIMIT 5;

Result:
- quantity <= 0: 14,466 rows (0.56% of total)
- sales_value <= 0: 18,850 rows (0.73% of total)
- Sample: product IDs 5978648 and 5978656 appear frequently, sometimes with coupon_disc = -1.0 or -2.0

My answer: Two different things are mixed here. Some rows are genuine returns (negative quantity). Others look like coupon line items — the product IDs in the 5,000,000+ range are UPCs that Dunnhumby uses to record coupon redemptions, not actual products. Both inflate counts if not filtered. Plan: exclude quantity <= 0 and sales_value <= 0 from sales aggregates and elasticity, but log the counts in tool output metadata. Investigate the 5M+ product ID range on Day 3.

## Open questions
- What counts as a "promo week" for a product? In this data, price discounts live in transaction_data, while display and mailer flags live in causal_data. Which one do I use, or both?