-- Mart: day x queue. contacts = demand (first legs); legs and workload = staffing input.
-- Service level = legs answered within 60 s / legs offered (abandons count against SL).

DROP TABLE IF EXISTS mart_daily_queue;
CREATE TABLE mart_daily_queue AS
WITH legs AS (
    SELECT arrival_date_local AS date, queue_name,
           COUNT(*)                                                       AS legs,
           SUM(CASE WHEN abandoned THEN 1 ELSE 0 END)                     AS abandoned,
           SUM(CASE WHEN NOT abandoned AND wait_sec <= 60 THEN 1 ELSE 0 END) AS answered_60,
           SUM(handle_time_sec)                                           AS workload_sec,
           AVG(CASE WHEN NOT abandoned THEN handle_time_sec END)          AS aht_sec
    FROM stg_call_leg
    GROUP BY arrival_date_local, queue_name
),
contacts AS (
    SELECT arrival_date_local AS date, first_queue AS queue_name, COUNT(*) AS contacts
    FROM fct_contact GROUP BY arrival_date_local, first_queue
),
grid AS (
    SELECT f.date, q.queue_name, f.is_closed, f.is_missing_data
    FROM mart_daily_features f CROSS JOIN stg_queue q
    WHERE f.date <= DATE '2025-12-31'
)
SELECT
    g.date, g.queue_name, g.is_closed, g.is_missing_data,
    CASE WHEN g.is_missing_data THEN NULL ELSE COALESCE(c.contacts, 0) END AS contacts,
    CASE WHEN g.is_missing_data THEN NULL ELSE COALESCE(l.legs, 0) END     AS legs,
    l.abandoned, l.answered_60, l.workload_sec, l.aht_sec
FROM grid g
LEFT JOIN legs l     ON l.date = g.date AND l.queue_name = g.queue_name
LEFT JOIN contacts c ON c.date = g.date AND c.queue_name = g.queue_name;
