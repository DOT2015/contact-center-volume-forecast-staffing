# Power BI model

`make powerbi` writes a star schema to `powerbi/csv/`. The export is about 4 MB and is committed. No `.pbix` file is included.

| Table | Grain | Keys |
|---|---|---|
| fact_interval_queue | day x half-hour x queue (open hours, 2024-2025) | date, slot48, queue_id |
| fact_daily_queue | day x queue (2024-2025) | date, queue_id |
| fact_forecast_daily | day x queue x scenario (Q1 2026) | date, queue_id, scenario |
| fact_staffing_weekly | week x scenario (Q1 2026) | week_start, scenario |
| dim_date | day, with event flags | date |
| dim_queue | queue | queue_id |

## Load

1. Get Data > Text/CSV, and load the six files.
2. Relationships (many-to-one, single direction): each fact's `date` -> `dim_date[date]`; each fact's `queue_id` -> `dim_queue[queue_id]`. Mark `dim_date` as the date table.
3. Add `scenario` as a slicer (baseline / price_notice).

## DAX measures

```DAX
Legs = SUM ( fact_interval_queue[legs] )
Service Level = DIVIDE ( SUM ( fact_interval_queue[answered_60] ), [Legs] )
Abandon Rate = DIVIDE ( SUM ( fact_interval_queue[abandoned] ), [Legs] )
Occupancy = DIVIDE ( SUM ( fact_interval_queue[workload_sec] ) / 3600,
                     SUM ( fact_interval_queue[agents_available] ) * 0.5 )
Forecast Legs = SUM ( fact_forecast_daily[forecast_legs] )
Required FTE = SUM ( fact_staffing_weekly[required_fte] )
FTE Gap = SUM ( fact_staffing_weekly[fte_gap] )
```

The backtest metrics and Erlang C requirements are computed in Python (`src/analysis.py`, `src/erlang.py`). Power BI only displays them.
