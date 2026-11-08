-- Q2. Billing-queue contacts on cycle days (days 1-3 after the 1st and 15th bill dates) vs. other days.
-- Compared within weekday so the day-of-week mix does not bias the ratio; 2024 and 2025 separately to
-- show stability. src/analysis.py also estimates the lift in a Poisson regression with trend and DOW.

WITH d AS (
    SELECT q.date, f.dow, EXTRACT(year FROM q.date) AS yr, f.is_billing_cycle_day, q.contacts
    FROM mart_daily_queue q
    JOIN mart_daily_features f ON f.date = q.date
    WHERE q.queue_name = 'billing' AND NOT q.is_closed AND NOT q.is_missing_data
      AND NOT f.is_holiday_open AND f.days_since_notice IS NULL
),
by_dow AS (
    SELECT yr, dow,
           AVG(CASE WHEN is_billing_cycle_day THEN contacts END)     AS cycle_avg,
           AVG(CASE WHEN NOT is_billing_cycle_day THEN contacts END) AS other_avg,
           SUM(CASE WHEN is_billing_cycle_day THEN 1 ELSE 0 END)     AS cycle_days
    FROM d GROUP BY yr, dow
)
SELECT yr, dow, cycle_days, cycle_avg, other_avg, cycle_avg / other_avg - 1 AS lift
FROM by_dow
UNION ALL
SELECT yr, 'ALL (cycle-day weighted)', SUM(cycle_days), NULL, NULL,
       SUM(cycle_days * (cycle_avg / other_avg - 1)) / SUM(cycle_days)
FROM by_dow GROUP BY yr
ORDER BY yr, dow;
