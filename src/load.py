"""Load raw CSVs into DuckDB (data/warehouse.duckdb) as raw_<table>, then build staging and marts.

Usage:
  python src/load.py --raw-only        # load CSVs into raw_* tables (make load)
  python src/load.py --transform-only  # run sql/01_staging then sql/02_marts (make clean)
  python src/load.py                   # both
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "warehouse.duckdb"

TYPES = {
    "fact_call_leg": {"arrival_ts": "TIMESTAMP", "answered_ts": "TIMESTAMP", "ended_ts": "TIMESTAMP", "queue_code": "VARCHAR"},
    "fact_staffing_interval": {"interval_start": "TIMESTAMP"},
    "fact_outage": {"start_ts": "TIMESTAMP", "end_ts": "TIMESTAMP"},
    "dim_date": {"date": "DATE"},
    "dim_business_event": {"event_date": "DATE"},
}


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB))


def run_sql_dir(con, folder: Path) -> None:
    for f in sorted(folder.glob("*.sql")):
        con.execute(f.read_text())
        print(f"  ran {f.relative_to(ROOT)}")


def main() -> None:
    if "--transform-only" in sys.argv:
        con = connect()
        run_sql_dir(con, ROOT / "sql" / "01_staging")
        run_sql_dir(con, ROOT / "sql" / "02_marts")
        con.close()
        return
    if DB.exists():
        DB.unlink()
    con = connect()
    for csv in sorted(RAW.glob("*.csv")):
        name = csv.stem
        types = TYPES.get(name, {})
        type_sql = ", ".join(f"'{k}': '{v}'" for k, v in types.items())
        opt = f", types={{{type_sql}}}" if types else ""
        con.execute(f"CREATE TABLE raw_{name} AS SELECT * FROM read_csv('{csv}', header=true{opt})")
        n = con.execute(f"SELECT COUNT(*) FROM raw_{name}").fetchone()[0]
        print(f"  loaded raw_{name}: {n:,} rows")
    if "--raw-only" not in sys.argv:
        run_sql_dir(con, ROOT / "sql" / "01_staging")
        run_sql_dir(con, ROOT / "sql" / "02_marts")
    con.close()


if __name__ == "__main__":
    main()
