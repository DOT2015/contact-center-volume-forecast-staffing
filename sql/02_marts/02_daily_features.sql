-- Mart: one row per calendar day 2024-01-01 .. 2026-03-31 with the regressors used in forecasting.
-- Business calendar facts (known in advance): bill dates are the 1st and 15th; promotions run 7 days;
-- a price notice is followed by a 10-day response window.

DROP TABLE IF EXISTS mart_daily_features;
CREATE TABLE mart_daily_features AS
WITH days AS (
    SELECT d.date, d.dow, d.is_holiday, d.is_dst_transition FROM raw_dim_date d
),
closed AS (SELECT event_date FROM stg_business_event WHERE is_closed),
hol_open AS (SELECT event_date FROM stg_business_event WHERE event_type = 'holiday' AND NOT is_closed),
promo AS (SELECT event_date FROM stg_business_event WHERE event_type = 'promo'),
notice AS (SELECT event_date FROM stg_business_event WHERE event_type = 'price_notice'),
outage_day AS (
    SELECT CAST(start_local AS DATE) AS date, SUM(customers_affected) AS outage_customers, COUNT(*) AS outages
    FROM stg_outage GROUP BY CAST(start_local AS DATE)
),
loaded AS (SELECT DISTINCT arrival_date_local AS date FROM stg_call_leg)
SELECT
    d.date,
    d.dow,
    EXTRACT(day FROM d.date)                                                   AS day_of_month,
    (d.date IN (SELECT event_date FROM closed))                                AS is_closed,
    (d.date IN (SELECT event_date FROM hol_open))                              AS is_holiday_open,
    (EXTRACT(day FROM d.date) IN (2, 3, 4, 16, 17, 18))                        AS is_billing_cycle_day,
    EXISTS (SELECT 1 FROM promo p WHERE d.date BETWEEN p.event_date AND p.event_date + 6) AS is_promo,
    (SELECT MIN(d.date - n.event_date) FROM notice n
      WHERE d.date - n.event_date BETWEEN 0 AND 9)                             AS days_since_notice,
    COALESCE(o.outage_customers, 0)                                            AS outage_customers,
    COALESCE(o.outages, 0)                                                     AS outages,
    d.is_dst_transition,
    (d.date <= DATE '2025-12-31'
        AND d.date NOT IN (SELECT event_date FROM closed)
        AND d.date NOT IN (SELECT date FROM loaded))                           AS is_missing_data
FROM days d
LEFT JOIN outage_day o ON o.date = d.date;
