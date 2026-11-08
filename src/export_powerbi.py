"""Export a Power BI star schema to powerbi/csv/ (committed if small) and refresh data/sample/."""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "powerbi" / "csv"
SAMPLE = ROOT / "data" / "sample"

QUERIES = {
    "dim_date": "SELECT * FROM mart_daily_features",
    "dim_queue": "SELECT * FROM stg_queue",
    "fact_daily_queue": "SELECT q.queue_id, d.* EXCLUDE (queue_name) FROM mart_daily_queue d JOIN stg_queue q USING (queue_name)",
    "fact_interval_queue": "SELECT * EXCLUDE (queue_name) FROM mart_interval_queue WHERE slot48 BETWEEN 14 AND 41",
    "fact_forecast_daily": """SELECT f.date, q.queue_id, f.scenario, f.mean AS forecast_legs, f.lo80, f.hi80
                              FROM read_csv('reports/tables/forecast_daily_q1_2026.csv') f
                              JOIN stg_queue q ON q.queue_name = f.queue""",
    "fact_staffing_weekly": "SELECT * FROM read_csv('reports/tables/06_staffing_requirement.csv')",
}


def main():
    con = duckdb.connect(str(DB), read_only=True)
    con.execute(f"SET file_search_path = '{ROOT}'")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, q in QUERIES.items():
        con.execute(f"COPY ({q}) TO '{OUT / (name + '.csv')}' (HEADER, DELIMITER ',')")
    SAMPLE.mkdir(parents=True, exist_ok=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'raw_%'").fetchall():
        con.execute(f"COPY (SELECT * FROM {t} USING SAMPLE 1000 ROWS (reservoir, 42)) "
                    f"TO '{SAMPLE / (t[4:] + '.csv')}' (HEADER, DELIMITER ',')")
    size = sum(f.stat().st_size for f in OUT.glob("*.csv")) / 1e6
    print(f"powerbi/csv: {len(QUERIES)} tables, {size:.1f} MB; data/sample refreshed")


if __name__ == "__main__":
    main()
