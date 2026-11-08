-- Staging: call legs.
-- Planted issues fixed here:
--  1. arrival/answered/ended_ts are UTC, EXCEPT rows before the 2024-04-01 migration, which were stored as
--     America/Chicago wall time. Those rows are converted local -> UTC; then every row gets a local version.
--     (Rule: raw arrival_ts < 2024-04-01 00:00. The first true-UTC row is 2024-04-01 12:00 UTC = 07:00 local,
--     so the boundary is unambiguous. The center is closed 21:00-07:00, so DST gaps/repeats never hit a call.)
--  2. Queue codes mapped to 5 canonical queues through ref_queue_code.
--  3. 0.6% of abandoned legs carry handle_time_sec > 0 -> set to 0 (flagged).

DROP TABLE IF EXISTS stg_call_leg;
CREATE TABLE stg_call_leg AS
WITH typed AS (
    SELECT
        l.*,
        (l.arrival_ts < TIMESTAMP '2024-04-01 00:00:00') AS stored_as_local
    FROM raw_fact_call_leg l
),
utc AS (
    SELECT
        t.*,
        CASE WHEN stored_as_local THEN (arrival_ts  AT TIME ZONE 'America/Chicago') AT TIME ZONE 'UTC' ELSE arrival_ts  END AS arrival_utc,
        CASE WHEN stored_as_local THEN (answered_ts AT TIME ZONE 'America/Chicago') AT TIME ZONE 'UTC' ELSE answered_ts END AS answered_utc,
        CASE WHEN stored_as_local THEN (ended_ts    AT TIME ZONE 'America/Chicago') AT TIME ZONE 'UTC' ELSE ended_ts    END AS ended_utc
    FROM typed t
)
SELECT
    u.leg_id,
    u.contact_id,
    u.customer_id,
    u.queue_code                                                    AS queue_code_raw,
    r.queue_name,
    q.queue_id,
    u.arrival_utc,
    u.answered_utc,
    u.ended_utc,
    (u.arrival_utc AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago' AS arrival_local,
    CAST((u.arrival_utc AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago' AS DATE) AS arrival_date_local,
    EXTRACT(EPOCH FROM (u.answered_utc - u.arrival_utc))            AS wait_sec,
    CASE WHEN u.abandoned_flag = 1 THEN 0 ELSE u.handle_time_sec END AS handle_time_sec,
    (u.abandoned_flag = 1 AND u.handle_time_sec > 0)                AS handle_time_fixed_flag,
    (u.abandoned_flag = 1)                                          AS abandoned,
    (u.transfer_flag = 1)                                           AS transferred_out,
    u.reason_code,
    u.stored_as_local                                               AS tz_fixed_flag
FROM utc u
LEFT JOIN ref_queue_code r ON r.queue_code = u.queue_code
LEFT JOIN stg_queue q      ON q.queue_name = r.queue_name;
