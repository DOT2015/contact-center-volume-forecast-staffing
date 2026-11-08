-- Q3. Tech-support contacts in the 4 hours after each outage starts vs. customers affected.
-- Baseline = average tech-support contacts in the same 4-hour clock window on the same weekday
-- in the 4 previous weeks. Excess = observed - baseline. Slope (calls per affected customer) is fitted
-- in src/analysis.py by least squares through the origin.

WITH tech AS (
    SELECT arrival_local FROM fct_contact WHERE first_queue = 'tech_support'
),
windows AS (
    SELECT o.outage_id, o.customers_affected, o.region, o.start_local, w.k,
           o.start_local - w.k * INTERVAL '7 days' AS win_start
    FROM stg_outage o
    CROSS JOIN (VALUES (0), (1), (2), (3), (4)) AS w(k)
),
counts AS (
    SELECT w.outage_id, w.k, COUNT(t.arrival_local) AS calls
    FROM windows w
    LEFT JOIN tech t ON t.arrival_local >= w.win_start AND t.arrival_local < w.win_start + INTERVAL '4 hours'
    GROUP BY w.outage_id, w.k
),
missing_weeks AS (   -- prior-week windows before 2024-01-01 or on missing-data/closed days are dropped
    SELECT w.outage_id, w.k FROM windows w
    LEFT JOIN mart_daily_features f ON f.date = CAST(w.win_start AS DATE)
    WHERE f.date IS NULL OR f.is_missing_data OR f.is_closed
)
SELECT
    o.outage_id, o.region, o.start_local, o.customers_affected,
    MAX(CASE WHEN c.k = 0 THEN c.calls END)                          AS observed_calls_4h,
    AVG(CASE WHEN c.k > 0 THEN CAST(c.calls AS DOUBLE) END)          AS baseline_calls_4h,
    MAX(CASE WHEN c.k = 0 THEN c.calls END)
      - AVG(CASE WHEN c.k > 0 THEN CAST(c.calls AS DOUBLE) END)      AS excess_calls_4h
FROM stg_outage o
JOIN counts c ON c.outage_id = o.outage_id
LEFT JOIN missing_weeks m ON m.outage_id = c.outage_id AND m.k = c.k
WHERE m.outage_id IS NULL
GROUP BY o.outage_id, o.region, o.start_local, o.customers_affected
ORDER BY o.start_local;
