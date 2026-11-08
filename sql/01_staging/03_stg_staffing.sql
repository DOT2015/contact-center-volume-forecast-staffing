-- Staging: staffing intervals. interval_start is America/Chicago wall time, 48 rows per day per queue.
-- DST artifacts: the fall-back Sunday has 01:00 and 01:30 twice; the spring-forward Sunday has no 02:00/02:30.
-- Both fall in closed hours (0 agents). Duplicates are collapsed with MAX so (interval_start, queue_id) is unique.

DROP TABLE IF EXISTS stg_staffing_interval;
CREATE TABLE stg_staffing_interval AS
SELECT
    interval_start                                         AS interval_start_local,
    CAST(interval_start AS DATE)                           AS interval_date,
    queue_id,
    MAX(agents_scheduled)                                  AS agents_scheduled,
    MAX(agents_available)                                  AS agents_available,
    COUNT(*)                                               AS source_rows
FROM raw_fact_staffing_interval
GROUP BY interval_start, queue_id;
