"""Build a local DuckDB database from the raw Dunnhumby CSV files.

Run from the repo root:

    python -m retail_memory.data.load

The database is a derived artifact (data/processed/, git-ignored). Delete it any time
and rebuild it with the command above.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_DB_PATH = Path("data/processed/retail.duckdb")

RAW_FILES: dict[str, str] = {
    "transactions": "transaction_data.csv",
    "causal": "causal_data.csv",
    "product": "product.csv",
    "hh_demographic": "hh_demographic.csv",
    "campaign_desc": "campaign_desc.csv",
    "campaign_table": "campaign_table.csv",
    "coupon": "coupon.csv",
    "coupon_redempt": "coupon_redempt.csv",
}

TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "transactions": ("TRANS_TIME",),
    "causal": ("display", "mailer"),
}


def _sql_quote(text: str) -> str:
    return text.replace("'", "''")


def _reader_sql(table: str, csv_path: Path) -> str:
    args = [f"'{_sql_quote(csv_path.as_posix())}'"]
    text_columns = TEXT_COLUMNS.get(table, ())
    if text_columns:
        types = ", ".join(f"'{col}': 'VARCHAR'" for col in text_columns)
        args.append(f"types={{{types}}}")
    return f"read_csv({', '.join(args)})"


def _load_table(con: duckdb.DuckDBPyConnection, table: str, csv_path: Path) -> int:
    reader = _reader_sql(table, csv_path)
    columns = [row[0] for row in con.sql(f"DESCRIBE SELECT * FROM {reader}").fetchall()]
    select_list = ", ".join(f'"{col}" AS "{col.lower()}"' for col in columns)
    con.execute(f"CREATE TABLE {table} AS SELECT {select_list} FROM {reader}")
    return con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def build_database(
    raw_dir: Path = DEFAULT_RAW_DIR,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    raw_dir = Path(raw_dir)
    db_path = Path(db_path)

    missing = [name for name in RAW_FILES.values() if not (raw_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing files in {raw_dir}: {', '.join(missing)}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in (db_path, Path(f"{db_path}.wal")):
        stale.unlink(missing_ok=True)

    counts: dict[str, int] = {}
    con = duckdb.connect(str(db_path))
    try:
        for table, file_name in RAW_FILES.items():
            counts[table] = _load_table(con, table, raw_dir / file_name)
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the retail DuckDB database.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args(argv)

    counts = build_database(args.raw_dir, args.db_path)
    print(f"Built {args.db_path}")
    for table, n in counts.items():
        print(f"  {table:<16}{n:>12,}")


if __name__ == "__main__":
    main()