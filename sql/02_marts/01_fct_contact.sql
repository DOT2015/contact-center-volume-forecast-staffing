-- Mart: contacts (demand) vs. legs (workload).
-- A contact is one customer call; a transfer creates another leg of the same contact in a second queue.
-- Demand forecasts count contacts by their first queue. Staffing counts legs in every queue they touch.

DROP TABLE IF EXISTS fct_contact;
CREATE TABLE fct_contact AS
WITH ordered AS (
    SELECT l.*, ROW_NUMBER() OVER (PARTITION BY contact_id ORDER BY arrival_utc, leg_id) AS leg_seq,
           COUNT(*) OVER (PARTITION BY contact_id) AS n_legs
    FROM stg_call_leg l
)
SELECT contact_id, customer_id, queue_name AS first_queue, arrival_local, arrival_date_local, n_legs,
       abandoned AS first_leg_abandoned
FROM ordered
WHERE leg_seq = 1;
