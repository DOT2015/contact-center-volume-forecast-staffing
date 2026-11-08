-- Mart: local half-hour interval x queue: arrivals, answered within 60 s, abandons, and agents.

DROP TABLE IF EXISTS mart_interval_queue;
CREATE TABLE mart_interval_queue AS
WITH legs AS (
    SELECT
        arrival_date_local AS date,
        queue_id,
        CAST(EXTRACT(hour FROM arrival_local) * 2 + FLOOR(EXTRACT(minute FROM arrival_local) / 30) AS INTEGER) AS slot48,
        COUNT(*)                                                          AS legs,
        SUM(CASE WHEN NOT abandoned AND wait_sec <= 60 THEN 1 ELSE 0 END) AS answered_60,
        SUM(CASE WHEN abandoned THEN 1 ELSE 0 END)                        AS abandoned,
        SUM(handle_time_sec)                                              AS workload_sec
    FROM stg_call_leg
    GROUP BY 1, 2, 3
),
staff AS (
    SELECT interval_date AS date, queue_id,
           CAST(EXTRACT(hour FROM interval_start_local) * 2 + FLOOR(EXTRACT(minute FROM interval_start_local) / 30) AS INTEGER) AS slot48,
           agents_scheduled, agents_available
    FROM stg_staffing_interval
)
SELECT
    s.date, s.queue_id, q.queue_name, s.slot48,
    LPAD(CAST(CAST(FLOOR(s.slot48 / 2.0) AS INTEGER) AS VARCHAR), 2, '0') || ':' || CASE WHEN s.slot48 % 2 = 0 THEN '00' ELSE '30' END AS interval_label,
    s.agents_scheduled, s.agents_available,
    COALESCE(l.legs, 0) AS legs, COALESCE(l.answered_60, 0) AS answered_60,
    COALESCE(l.abandoned, 0) AS abandoned, COALESCE(l.workload_sec, 0) AS workload_sec
FROM staff s
JOIN stg_queue q ON q.queue_id = s.queue_id
LEFT JOIN legs l ON l.date = s.date AND l.queue_id = s.queue_id AND l.slot48 = s.slot48;
