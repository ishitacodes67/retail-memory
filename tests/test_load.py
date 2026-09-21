"""Tests for the DuckDB loader, using tiny fake CSVs (real data is never in the repo)."""

from pathlib import Path

import duckdb
import pytest

from retail_memory.data.load import RAW_FILES, build_database

# Same headers (and header casing) as the real Dunnhumby files, two rows each.
FIXTURES: dict[str, str] = {
    "transaction_data.csv": (
        "household_key,BASKET_ID,DAY,PRODUCT_ID,QUANTITY,SALES_VALUE,STORE_ID,"
        "RETAIL_DISC,TRANS_TIME,WEEK_NO,COUPON_DISC,COUPON_MATCH_DISC\n"
        "1,100,1,10,1,1.39,5,-0.6,0040,1,0,0\n"
        "1,100,1,11,2,3.78,5,0,0040,1,-1.0,0\n"
    ),
    "causal_data.csv": (
        "PRODUCT_ID,STORE_ID,WEEK_NO,display,mailer\n"
        "10,5,1,0,A\n"
        "11,5,1,3,0\n"
    ),
    "product.csv": (
        "PRODUCT_ID,MANUFACTURER,DEPARTMENT,BRAND,COMMODITY_DESC,SUB_COMMODITY_DESC,"
        "CURR_SIZE_OF_PRODUCT\n"
        "10,2,GROCERY,Private,SOUP,CANNED SOUP,10 OZ\n"
        "11,3,GROCERY,National,SOUP,DRY SOUP,5 OZ\n"
    ),
    "hh_demographic.csv": (
        "AGE_DESC,MARITAL_STATUS_CODE,INCOME_DESC,HOMEOWNER_DESC,HH_COMP_DESC,"
        "HOUSEHOLD_SIZE_DESC,KID_CATEGORY_DESC,household_key\n"
        "25-34,A,50-74K,Homeowner,2 Adults No Kids,2,None/Unknown,1\n"
        "35-44,B,35-49K,Renter,Single Male,1,None/Unknown,2\n"
    ),
    "campaign_desc.csv": (
        "DESCRIPTION,CAMPAIGN,START_DAY,END_DAY\n"
        "TypeA,1,100,150\n"
        "TypeB,2,200,250\n"
    ),
    "campaign_table.csv": (
        "DESCRIPTION,household_key,CAMPAIGN\n"
        "TypeA,1,1\n"
        "TypeB,2,2\n"
    ),
    "coupon.csv": (
        "COUPON_UPC,PRODUCT_ID,CAMPAIGN\n"
        "1001,10,1\n"
        "1002,11,2\n"
    ),
    "coupon_redempt.csv": (
        "household_key,DAY,COUPON_UPC,CAMPAIGN\n"
        "1,120,1001,1\n"
        "2,210,1002,2\n"
    ),
}


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "raw"
    directory.mkdir()
    for name, text in FIXTURES.items():
        (directory / name).write_text(text)
    return directory


def test_fixtures_cover_every_expected_file():
    assert set(FIXTURES) == set(RAW_FILES.values())


def test_build_returns_row_counts(raw_dir: Path, tmp_path: Path):
    counts = build_database(raw_dir, tmp_path / "test.duckdb")
    assert counts == {table: 2 for table in RAW_FILES}


def test_column_names_are_lowercase(raw_dir: Path, tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    build_database(raw_dir, db_path)
    with duckdb.connect(str(db_path), read_only=True) as con:
        for table in RAW_FILES:
            columns = [row[0] for row in con.sql(f"DESCRIBE {table}").fetchall()]
            assert columns == [c.lower() for c in columns], table
        first = con.sql("SELECT basket_id FROM transactions LIMIT 1").fetchone()
    assert first is not None


def test_code_columns_stay_text(raw_dir: Path, tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    build_database(raw_dir, db_path)
    with duckdb.connect(str(db_path), read_only=True) as con:
        trans_time = con.sql(
            "SELECT trans_time FROM transactions ORDER BY product_id LIMIT 1"
        ).fetchone()[0]
        types = dict(con.sql("SELECT column_name, column_type FROM (DESCRIBE causal)").fetchall())
    assert trans_time == "0040"  # leading zeros survive
    assert types["display"] == "VARCHAR"
    assert types["mailer"] == "VARCHAR"


def test_missing_file_raises_clear_error(raw_dir: Path, tmp_path: Path):
    (raw_dir / "product.csv").unlink()
    with pytest.raises(FileNotFoundError, match="product.csv"):
        build_database(raw_dir, tmp_path / "test.duckdb")


def test_rebuild_replaces_old_database(raw_dir: Path, tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    build_database(raw_dir, db_path)
    counts = build_database(raw_dir, db_path)
    assert counts["transactions"] == 2  # not 4: the old database was replaced