import duckdb
import pandas as pd
from retail_memory.tools.elasticity import estimate_elasticity

def main():
    con = duckdb.connect("data/processed/retail.duckdb", read_only=True)
    
    candidates = con.sql("""
        SELECT product_id FROM product_week
        GROUP BY product_id
        HAVING COUNT(*) >= 30
           AND SUM(is_price_promo_any_store::INT) >= 5
           AND SUM((NOT is_price_promo_any_store)::INT) >= 5
        ORDER BY SUM(total_quantity) DESC
        LIMIT 30
    """).df()

    results = []
    for pid in candidates["product_id"]:
        est = estimate_elasticity(con, int(pid))
        results.append({
            "product_id": int(pid), "method": est.method, "confidence": est.confidence,
            "coefficient": est.coefficient, "ci_low": est.ci_low, "ci_high": est.ci_high,
        })

    results_df = pd.DataFrame(results)
    print(results_df["confidence"].value_counts())
    print("\nHigh confidence products:")
    print(results_df[results_df["confidence"] == "high"].to_string(index=False))

if __name__ == "__main__":
    main()