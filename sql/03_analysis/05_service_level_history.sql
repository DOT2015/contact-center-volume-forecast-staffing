-- Q5. Weekly service level (answered within 60 s / offered legs) and abandonment vs. staffing,
-- plus interval-level SL by staffing ratio (agents available per Erlang of offered load).

WITH wk AS (
    SELECT
        CAST(date - CAST(EXTRACT(isodow FROM date) - 1 AS INTEGER) AS DATE) AS week_start,
        SUM(legs) AS legs, SUM(answered_60) AS answered_60, SUM(abandoned) AS abandoned,
        SUM(agents_available) * 0.5 AS available_agent_hours,
        SUM(agents_scheduled) * 0.5 AS scheduled_agent_hours,
        SUM(workload_sec) / 3600.0  AS handled_hours
    FROM mart_interval_queue
    WHERE date <= DATE '2025-12-31'
    GROUP BY 1
)
SELECT
    week_start, legs,
    CAST(answered_60 AS DOUBLE) / NULLIF(legs, 0)        AS service_level,
    CAST(abandoned AS DOUBLE) / NULLIF(legs, 0)          AS abandon_rate,
    scheduled_agent_hours, available_agent_hours,
    handled_hours / NULLIF(available_agent_hours, 0)     AS occupancy
FROM wk
WHERE legs > 0
ORDER BY week_start;
