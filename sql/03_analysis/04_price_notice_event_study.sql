-- Q4. Event study around the 2025-09-15 price-change notice: billing + cancellations contacts per day.
-- Simple counterfactual here = average of the same weekday in the 4 weeks before the notice, with the
-- billing-cycle days handled separately (cycle days compared with prior cycle days of any weekday,
-- scaled by the weekday index). src/analysis.py replaces this with a Poisson-regression counterfactual
-- (trend, DOW, billing cycle) and fits the lift and half-life.

WITH d AS (
    SELECT q.date, f.dow, f.is_billing_cycle_day, SUM(q.contacts) AS contacts,
           SUM(q.workload_sec) / NULLIF(SUM(q.legs - q.abandoned), 0) AS aht_sec
    FROM mart_daily_queue q JOIN mart_daily_features f ON f.date = q.date
    WHERE q.queue_name IN ('billing', 'cancellations')
      AND q.date BETWEEN DATE '2025-08-04' AND DATE '2025-10-26'
    GROUP BY q.date, f.dow, f.is_billing_cycle_day
),
base AS (
    SELECT dow, AVG(CAST(contacts AS DOUBLE)) AS dow_avg, AVG(aht_sec) AS aht_avg
    FROM d WHERE date BETWEEN DATE '2025-08-18' AND DATE '2025-09-14' AND NOT is_billing_cycle_day
    GROUP BY dow
)
SELECT
    d.date, d.dow, d.is_billing_cycle_day,
    CAST(d.date - DATE '2025-09-15' AS INTEGER)    AS days_from_notice,
    d.contacts,
    b.dow_avg                                      AS naive_counterfactual,
    d.contacts / b.dow_avg - 1                     AS naive_excess_ratio,
    d.aht_sec,
    d.aht_sec / b.aht_avg - 1                      AS aht_change
FROM d JOIN base b ON b.dow = d.dow
ORDER BY d.date;
