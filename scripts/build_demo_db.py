"""Builds the small, deployable database: derived/aggregate tables only. No raw
per-transaction data, no causal_data. See D-022 for the dataset-terms rationale.
"""
import duckdb
from pathlib import Path

SOURCE_DB = "data/processed/retail.duckdb"
DEMO_DB = "data/processed/demo.duckdb"
DEMO_TABLES = ["product", "product_week", "product_store_week", "product_quantity_profile"]

def build_demo_db(source=SOURCE_DB, dest=DEMO_DB):
    Path(dest).unlink(missing_ok=True)
    src = duckdb.connect(source, read_only=True)
    dst = duckdb.connect(dest)
    for table in DEMO_TABLES:
        # For product_store_week, we might filter to only products with actual sales
        # to keep the size small. But let's check the raw size first.
        df = src.sql(f"SELECT * FROM {table}").df()
        dst.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
        print(f"  {table}: {len(df):,} rows")
    src.close()
    dst.close()
    size_mb = Path(dest).stat().st_size / 1e6
    print(f"Built {dest}: {size_mb:.1f} MB")

if __name__ == "__main__":
    build_demo_db()