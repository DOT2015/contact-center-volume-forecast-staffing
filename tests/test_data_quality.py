"""Row counts, uniqueness, referential integrity, null thresholds, and cleaning rules."""
from conftest import scalar


def test_row_counts(con, truth):
    for t, n in truth["realized"]["rows"].items():
        assert scalar(con, f"SELECT COUNT(*) FROM raw_{t}") == n, t
    assert 50_000 <= truth["realized"]["rows"]["fact_call_leg"] <= 500_000
    assert truth["realized"]["rows"]["dim_date"] == 821


def test_two_years_covered(con):
    lo, hi = con.execute("SELECT MIN(arrival_date_local), MAX(arrival_date_local) FROM stg_call_leg").fetchone()
    assert str(lo) <= "2024-01-02"   # 2024-01-01 is a closed holiday
    assert str(hi) == "2025-12-31"


def test_keys_unique(con):
    for t, k in [("stg_call_leg", "leg_id"), ("fct_contact", "contact_id"), ("stg_customer", "customer_id"),
                 ("stg_outage", "outage_id")]:
        assert scalar(con, f"SELECT COUNT(*) - COUNT(DISTINCT {k}) FROM {t}") == 0, t
    assert scalar(con, """SELECT COUNT(*) FROM (SELECT interval_start_local, queue_id, COUNT(*) n
                          FROM stg_staffing_interval GROUP BY 1, 2 HAVING COUNT(*) > 1)""") == 0
    assert scalar(con, "SELECT COUNT(*) FROM (SELECT date, queue_name FROM mart_daily_queue GROUP BY 1, 2 HAVING COUNT(*) > 1)") == 0


def test_referential_integrity(con):
    assert scalar(con, "SELECT COUNT(*) FROM stg_call_leg l LEFT JOIN stg_customer c USING (customer_id) WHERE c.customer_id IS NULL") == 0
    assert scalar(con, "SELECT COUNT(*) FROM stg_call_leg WHERE queue_id IS NULL OR queue_name IS NULL") == 0


def test_null_thresholds(con):
    assert scalar(con, "SELECT COUNT(*) FROM stg_call_leg WHERE arrival_utc IS NULL OR ended_utc IS NULL") == 0
    # answered_ts is NULL exactly for abandoned legs
    assert scalar(con, "SELECT COUNT(*) FROM stg_call_leg WHERE (answered_utc IS NULL) <> abandoned") == 0


def test_timezone_fix(con):
    # after conversion every call lands inside opening hours (07:00-21:00 local)
    assert scalar(con, """SELECT COUNT(*) FROM stg_call_leg
                          WHERE EXTRACT(hour FROM arrival_local) < 7 OR EXTRACT(hour FROM arrival_local) >= 21""") == 0
    assert scalar(con, "SELECT SUM(CAST(tz_fixed_flag AS INT)) FROM stg_call_leg") > 0


def test_dst_artifacts(con):
    assert scalar(con, "SELECT SUM(source_rows - 1) FROM stg_staffing_interval") == 4 * 5  # 2 falls x 2 slots x 5 queues
    assert scalar(con, """SELECT COUNT(*) FROM raw_fact_staffing_interval
                          WHERE interval_start IN (TIMESTAMP '2024-03-10 02:00:00', TIMESTAMP '2025-03-09 02:30:00')""") == 0


def test_abandoned_handle_time_zero(con):
    assert scalar(con, "SELECT COUNT(*) FROM stg_call_leg WHERE abandoned AND handle_time_sec > 0") == 0


def test_missing_days_flagged(con, truth):
    got = [str(r[0]) for r in con.execute("SELECT date FROM mart_daily_features WHERE is_missing_data ORDER BY date").fetchall()]
    assert got == truth["parameters"]["missing_days"]


def test_contacts_vs_legs(con):
    legs, contacts = con.execute("SELECT (SELECT COUNT(*) FROM stg_call_leg), (SELECT COUNT(*) FROM fct_contact)").fetchone()
    assert 1.03 < legs / contacts < 1.05
