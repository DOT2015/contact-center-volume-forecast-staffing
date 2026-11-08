-- Q1. Day-of-week x 30-minute interval arrival profile by queue (legs, center-local time).
-- Uses ordinary open days only (no holidays, promo or price-notice days, no missing-data days).
-- interval_index = mean legs in the interval / mean legs per open interval for that queue and weekday.
-- src/analysis.py uses the last 26 weeks of this profile to spread daily forecasts across intervals.

WITH normal_days AS (
    SELECT date, dow FROM mart_daily_features
    WHERE NOT is_closed AND NOT is_holiday_open AND NOT is_promo AND days_since_notice IS NULL
      AND NOT is_missing_data AND date <= DATE '2025-12-31'
),
cell AS (
    SELECT i.queue_name, n.dow, i.slot48, i.interval_label,
           AVG(CAST(i.legs AS DOUBLE)) AS avg_legs,
           SUM(CASE WHEN i.date >= DATE '2025-07-01' THEN i.legs ELSE 0 END) AS legs_last_26w
    FROM mart_interval_queue i
    JOIN normal_days n ON n.date = i.date
    WHERE i.slot48 BETWEEN 14 AND 41          -- 07:00 .. 20:30 local
    GROUP BY i.queue_name, n.dow, i.slot48, i.interval_label
)
SELECT
    queue_name, dow, slot48, interval_label, avg_legs,
    avg_legs / AVG(avg_legs) OVER (PARTITION BY queue_name, dow)                        AS interval_index,
    CAST(legs_last_26w AS DOUBLE) / SUM(legs_last_26w) OVER (PARTITION BY queue_name, dow) AS share_of_day_last_26w
FROM cell
ORDER BY queue_name, dow, slot48;
