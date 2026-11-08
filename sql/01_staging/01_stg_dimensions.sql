-- Staging: dimensions. Center time zone is America/Chicago.

DROP TABLE IF EXISTS stg_queue;
CREATE TABLE stg_queue AS
SELECT queue_id, LOWER(TRIM(queue_name)) AS queue_name, sl_target, sl_threshold_sec FROM raw_dim_queue;

-- Queue codes changed at the IVR migration on 2025-05-01; tech support also appears as 'TS'.
DROP TABLE IF EXISTS ref_queue_code;
CREATE TABLE ref_queue_code AS
SELECT t.queue_code, t.queue_name, t.code_era
FROM (VALUES
    ('BILL', 'billing', 'pre_ivr'),            ('Billing', 'billing', 'post_ivr'),
    ('TECH', 'tech_support', 'pre_ivr'),       ('Tech_Support', 'tech_support', 'post_ivr'),
    ('TS', 'tech_support', 'post_ivr_alias'),
    ('MOVE', 'moves_new_service', 'pre_ivr'),  ('Moves_NewService', 'moves_new_service', 'post_ivr'),
    ('CANC', 'cancellations', 'pre_ivr'),      ('Cancellations', 'cancellations', 'post_ivr'),
    ('OUTG', 'outage', 'pre_ivr'),             ('Outage', 'outage', 'post_ivr')
) AS t(queue_code, queue_name, code_era);

DROP TABLE IF EXISTS stg_customer;
CREATE TABLE stg_customer AS
SELECT customer_id, plan_tier, region, CAST(signup_date AS DATE) AS signup_date, bill_cycle FROM raw_dim_customer;

DROP TABLE IF EXISTS stg_business_event;
CREATE TABLE stg_business_event AS
SELECT event_date, LOWER(event_type) AS event_type, queues_affected, CAST(is_closed AS BOOLEAN) AS is_closed
FROM raw_dim_business_event;

-- Outage start/end are UTC; add center-local versions.
DROP TABLE IF EXISTS stg_outage;
CREATE TABLE stg_outage AS
SELECT
    outage_id, region, customers_affected,
    start_ts AS start_utc, end_ts AS end_utc,
    (start_ts AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago' AS start_local,
    (end_ts   AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago' AS end_local
FROM raw_fact_outage;
