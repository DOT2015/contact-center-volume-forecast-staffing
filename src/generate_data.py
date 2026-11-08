"""Generate the synthetic contact-center dataset (simulated regional home-internet provider).

All data is synthetic (seed 42). No real customers or organizations.

Outputs: data/raw/*.csv (7 tables, with planted data-quality issues) and data/truth/planted_effects.json.

Volume model (contacts = first legs):
  expected contacts(day d, queue q, interval i) =
      BASE[q] x DOW[d] x TREND(d) x EVENTS(d, q) x SHAPE[i] / 28
  arrivals ~ Poisson(expected). Outage calls are added on top for tech support.
Queueing: each half-hour cell is treated as M/M/c with the scheduled agents still available;
waits are drawn from the Erlang C waiting-time distribution, patience is exponential (mean 900 s).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CENTER_TZ, CLOSE_HOUR, OPEN_HOUR, QUEUES  # noqa: E402
from erlang import agents_required, erlang_c  # noqa: E402

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
RAW, TRUTH = ROOT / "data" / "raw", ROOT / "data" / "truth"

START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")
N_CUSTOMERS = 120_000
BASE_DAILY = 590.0                       # contacts per open day at 2024-01-01, all queues, mean DOW
QUEUE_SHARE = {"billing": 0.34, "tech_support": 0.38, "moves_new_service": 0.13, "cancellations": 0.09, "outage": 0.06}
DOW_RAW = {"Mon": 1.35, "Tue": 1.15, "Wed": 1.05, "Thu": 1.00, "Fri": 0.95, "Sat": 0.55, "Sun": 0.45}
DOW_NORM = np.array(list(DOW_RAW.values())) / np.mean(list(DOW_RAW.values()))  # mean 1 over open days
TREND_PER_MONTH = 0.006
BILLING_LIFT, BILLING_DAYS = 0.22, (1, 2, 3)          # days after the bill date (1st and 15th)
OUTAGE_CALLS_PER_CUSTOMER = 0.004
OUTAGE_SPREAD_HOURS, OUTAGE_DECAY_HOURS = 4.0, 1.0
NOTICE_DATE, NOTICE_LIFT, NOTICE_HALF_LIFE, NOTICE_DAYS = pd.Timestamp("2025-09-15"), 0.40, 3.0, 10
NOTICE_AHT_LIFT, NOTICE_AHT_DAYS = 0.08, 14
NOTICE_QUEUES = ("billing", "cancellations")
NOTICE_2026 = pd.Timestamp("2026-02-02")
AHT_MEDIAN_MIN = {"billing": 4.2, "tech_support": 6.5, "moves_new_service": 7.5, "cancellations": 5.5, "outage": 3.0}
AHT_SIGMA = 0.55
HOLIDAY_OPEN_FACTOR = 0.70
PROMO_LIFT, PROMO_DAYS = 0.15, 7                       # moves/new service
TRANSFER_SHARE = 0.04
PATIENCE_MEAN_SEC = 900
N_OUTAGES = 90
REGIONS = ["North", "South", "East", "West"]

# Intraday shape: 28 open intervals (07:00-20:30). Peaks fixed at 1.6x (10:00-11:30) and 1.3x (13:00-14:30)
# the interval mean; the remaining intervals follow a smooth curve rescaled so the mean is exactly 1.
SLOTS = [f"{h:02d}:{m:02d}" for h in range(OPEN_HOUR, CLOSE_HOUR) for m in (0, 30)]
PEAK1 = ["10:00", "10:30", "11:00"]
PEAK2 = ["13:00", "13:30", "14:00"]


def intraday_shape():
    t = np.arange(28) / 2 + OPEN_HOUR + 0.25
    base = 0.55 + 0.6 * np.exp(-((t - 11) / 2.2) ** 2) + 0.45 * np.exp(-((t - 14.5) / 2.5) ** 2) \
        + 0.25 * np.exp(-((t - 18.5) / 1.5) ** 2)
    s = np.zeros(28)
    fixed = {SLOTS.index(x): 1.6 for x in PEAK1} | {SLOTS.index(x): 1.3 for x in PEAK2}
    free = [i for i in range(28) if i not in fixed]
    for i, v in fixed.items():
        s[i] = v
    remaining = 28 - sum(fixed.values())
    s[free] = base[free] * remaining / base[free].sum()
    return s


SHAPE = intraday_shape()

HOLIDAYS_CLOSED = pd.to_datetime(["2024-01-01", "2024-11-28", "2024-12-25", "2025-01-01", "2025-11-27",
                                  "2025-12-25", "2026-01-01"])
HOLIDAYS_OPEN = pd.to_datetime(["2024-01-15", "2024-02-19", "2024-05-27", "2024-07-04", "2024-09-02",
                                "2025-01-20", "2025-02-17", "2025-05-26", "2025-07-04", "2025-09-01",
                                "2026-01-19", "2026-02-16"])
PROMOS = pd.to_datetime(["2024-03-04", "2024-05-13", "2024-08-19", "2024-10-07", "2025-03-03",
                         "2025-05-12", "2025-08-18", "2025-10-06", "2026-03-02"])
MISSING_DAYS = pd.to_datetime(["2024-08-12", "2024-08-13"])
IVR_CHANGE = pd.Timestamp("2025-05-01")
LOCAL_TS_UNTIL = pd.Timestamp("2024-04-01")  # arrival_ts stored as local time before this date
OLD_CODES = {"billing": "BILL", "tech_support": "TECH", "moves_new_service": "MOVE", "cancellations": "CANC",
             "outage": "OUTG"}
NEW_CODES = {"billing": "Billing", "tech_support": "Tech_Support", "moves_new_service": "Moves_NewService",
             "cancellations": "Cancellations", "outage": "Outage"}
REASONS = {"billing": ["BILL_QUESTION", "PAYMENT", "AUTOPAY", "LATE_FEE"],
           "tech_support": ["NO_INTERNET", "SLOW_SPEED", "WIFI", "EQUIPMENT"],
           "moves_new_service": ["NEW_SERVICE", "MOVE", "UPGRADE"],
           "cancellations": ["CANCEL", "RETENTION_OFFER", "PRICE"],
           "outage": ["OUTAGE_STATUS", "OUTAGE_CREDIT"]}


def notice_multiplier(dates: pd.DatetimeIndex, notice: pd.Timestamp) -> np.ndarray:
    k = (dates - notice).days.values
    return np.where((k >= 0) & (k < NOTICE_DAYS), 1 + NOTICE_LIFT * 0.5 ** (k / NOTICE_HALF_LIFE), 1.0)


def day_frame(start, end) -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    d["dow"] = d.date.dt.dayofweek
    d["open"] = ~d.date.isin(HOLIDAYS_CLOSED)
    d["months"] = (d.date - START).dt.days / (365.25 / 12)
    d["trend"] = (1 + TREND_PER_MONTH) ** d.months
    d["holiday_open"] = d.date.isin(HOLIDAYS_OPEN)
    d["billing_cycle_day"] = d.date.dt.day.isin([1 + k for k in BILLING_DAYS] + [15 + k for k in BILLING_DAYS])
    promo = np.zeros(len(d), bool)
    for p in PROMOS:
        promo |= ((d.date >= p) & (d.date < p + pd.Timedelta(days=PROMO_DAYS))).values
    d["promo"] = promo
    return d


def expected_contacts(days: pd.DataFrame, notice_dates=(NOTICE_DATE,)) -> pd.DataFrame:
    """Expected daily contacts per queue (without outages)."""
    rows = []
    for q, share in QUEUE_SHARE.items():
        m = BASE_DAILY * share * DOW_NORM[days.dow.values] * days.trend.values
        m = m * np.where(days.holiday_open, HOLIDAY_OPEN_FACTOR, 1.0) * days.open.values
        if q == "billing":
            m = m * np.where(days.billing_cycle_day, 1 + BILLING_LIFT, 1.0)
        if q == "moves_new_service":
            m = m * np.where(days.promo, 1 + PROMO_LIFT, 1.0)
        if q in NOTICE_QUEUES:
            for nd in notice_dates:
                m = m * notice_multiplier(pd.DatetimeIndex(days.date), nd)
        rows.append(pd.DataFrame({"date": days.date.values, "queue": q, "expected": m}))
    return pd.concat(rows, ignore_index=True)


def aht_multiplier(dates: pd.Series, queue: np.ndarray, notice=NOTICE_DATE) -> np.ndarray:
    k = (dates - notice).dt.days.values
    hit = (k >= 0) & (k < NOTICE_AHT_DAYS) & np.isin(queue, NOTICE_QUEUES)
    return np.where(hit, 1 + NOTICE_AHT_LIFT, 1.0)


def to_utc(local: pd.Series) -> pd.Series:
    return (local.dt.tz_localize(CENTER_TZ, ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC").dt.tz_localize(None))


def main():
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- customers
    cust = pd.DataFrame({"customer_id": [f"CU{i:06d}" for i in range(1, N_CUSTOMERS + 1)]})
    cust["plan_tier"] = rng.choice(["basic_100", "plus_300", "gig_1000"], N_CUSTOMERS, p=[0.45, 0.4, 0.15])
    cust["region"] = rng.choice(REGIONS, N_CUSTOMERS, p=[0.3, 0.25, 0.25, 0.2])
    # growth: ~13% of the base signed up during the history window
    pre = rng.random(N_CUSTOMERS) < 0.87
    signup = np.where(pre, (pd.Timestamp("2016-01-01") + pd.to_timedelta(rng.integers(0, 2922, N_CUSTOMERS), "D")).values,
                      (START + pd.to_timedelta(rng.integers(0, 731, N_CUSTOMERS), "D")).values)
    cust["signup_date"] = pd.to_datetime(signup)
    cust["bill_cycle"] = rng.choice([1, 15], N_CUSTOMERS)

    # ------------------------------------------------------------- outages
    odays = pd.date_range(START, END, freq="D")
    o_start = pd.Series(odays[rng.integers(0, len(odays), N_OUTAGES)]) + pd.to_timedelta(
        rng.uniform(OPEN_HOUR, 17, N_OUTAGES), unit="h")
    o_start = o_start.dt.floor("min")
    outages = pd.DataFrame({
        "outage_id": [f"O{i:03d}" for i in range(1, N_OUTAGES + 1)],
        "region": rng.choice(REGIONS, N_OUTAGES),
        "start_local": o_start,
        "customers_affected": np.round(rng.lognormal(np.log(3000), 0.9, N_OUTAGES)).astype(int).clip(150, 40000),
    })
    outages["end_local"] = outages.start_local + pd.to_timedelta(rng.uniform(0.5, 8, N_OUTAGES), unit="h")
    outages = outages[~outages.start_local.dt.normalize().isin(HOLIDAYS_CLOSED.union(MISSING_DAYS))]
    outages = outages.sort_values("start_local").reset_index(drop=True)

    # ------------------------------------------------------------- arrivals (first legs)
    days = day_frame(START, END)
    exp_d = expected_contacts(days)
    cells = exp_d.loc[exp_d.expected > 0].copy()
    cells = cells.loc[cells.index.repeat(28)].reset_index(drop=True)
    cells["slot"] = np.tile(np.arange(28), len(cells) // 28)
    cells["lam"] = cells.expected * SHAPE[cells.slot.values] / 28
    cells["n"] = rng.poisson(cells.lam.values)
    legs = cells.loc[cells.index.repeat(cells.n), ["date", "queue", "slot"]].reset_index(drop=True)
    legs["arrival_local"] = legs.date + pd.to_timedelta(OPEN_HOUR * 3600 + legs.slot * 1800
                                                         + rng.uniform(0, 1800, len(legs)), unit="s")
    legs["source"] = "base"
    # outage calls to tech support
    oc = []
    for o in outages.itertuples():
        k = rng.poisson(OUTAGE_CALLS_PER_CUSTOMER * o.customers_affected)
        # truncated exponential over the first 4 hours
        u = rng.random(k)
        lim = 1 - np.exp(-OUTAGE_SPREAD_HOURS / OUTAGE_DECAY_HOURS)
        t = -OUTAGE_DECAY_HOURS * np.log(1 - u * lim)
        ts = o.start_local + pd.to_timedelta(t, unit="h")
        oc.append(pd.DataFrame({"arrival_local": ts, "queue": "tech_support", "source": o.outage_id,
                                "region": o.region}))
    oc = pd.concat(oc, ignore_index=True)
    close = oc.arrival_local.dt.normalize() + pd.Timedelta(hours=CLOSE_HOUR)
    oc_realized_total = len(oc)
    oc = oc[oc.arrival_local < close]  # calls after closing are not offered
    oc["date"] = oc.arrival_local.dt.normalize()
    oc["slot"] = ((oc.arrival_local - oc.date).dt.total_seconds() // 1800 - OPEN_HOUR * 2).astype(int)
    legs = pd.concat([legs, oc], ignore_index=True)
    legs = legs.sort_values("arrival_local").reset_index(drop=True)
    n_contacts = len(legs)

    # customers: billing on cycle days draws from the matching cycle; outage calls from the outage region
    cust_active_until = cust.signup_date.values
    reg_idx = {r: np.where(cust.region.values == r)[0] for r in REGIONS}
    cyc_idx = {c: np.where(cust.bill_cycle.values == c)[0] for c in (1, 15)}
    pick = rng.integers(0, N_CUSTOMERS, n_contacts)
    is_reg = legs.region.notna().values
    for r in REGIONS:
        m = is_reg & (legs.region.values == r)
        pick[m] = reg_idx[r][rng.integers(0, len(reg_idx[r]), m.sum())]
    dom = legs.arrival_local.dt.day.values
    for c in (1, 15):
        m = (legs.queue.values == "billing") & np.isin(dom, [c + k for k in BILLING_DAYS]) & (rng.random(n_contacts) < 0.6)
        pick[m] = cyc_idx[c][rng.integers(0, len(cyc_idx[c]), m.sum())]
    # customers must have signed up before the call; re-draw from established customers otherwise
    late = cust_active_until[pick] > legs.arrival_local.values
    est = np.where(pre)[0]
    pick[late] = est[rng.integers(0, len(est), late.sum())]
    legs["customer_id"] = cust.customer_id.values[pick]
    legs["contact_id"] = [f"K{i:07d}" for i in range(1, n_contacts + 1)]
    legs["leg_no"] = 1

    # ------------------------------------------------------------- staffing plan (history)
    # The simulated planner staffs to Erlang C on a forecast that freezes the trend at the start of each
    # year (+2%) and ignores outages and the price notice. Unplanned absence removes ~5% of scheduled agents.
    plan_days = days.copy()
    plan_days["trend"] = (1 + TREND_PER_MONTH) ** (12 * (plan_days.date.dt.year - 2024)) * 1.02
    plan = expected_contacts(plan_days, notice_dates=())
    plan = plan.loc[plan.index.repeat(28)].reset_index(drop=True)
    plan["slot"] = np.tile(np.arange(28), len(plan) // 28)
    plan_aht = plan.queue.map({q: 60 * AHT_MEDIAN_MIN[q] * np.exp(AHT_SIGMA ** 2 / 2) for q in QUEUES})
    plan["calls"] = plan.expected * SHAPE[plan.slot.values] / 28 * 1.04  # transfers add ~4% workload
    plan["agents_scheduled"] = agents_required(plan.calls.values, plan_aht.values)
    plan.loc[plan.expected == 0, "agents_scheduled"] = 0
    plan["agents_scheduled"] = np.maximum(
        np.round(plan.agents_scheduled * rng.normal(1.0, 0.04, len(plan))), np.where(plan.expected > 0, 1, 0)).astype(int)
    absent = rng.binomial(plan.agents_scheduled.values, 0.05)
    plan["agents_available"] = np.maximum(plan.agents_scheduled - absent, np.minimum(plan.agents_scheduled, 1))

    # ------------------------------------------------------------- handle times and queueing
    def draw_handle(df):
        med = df.queue.map(AHT_MEDIAN_MIN).values * 60
        h = rng.lognormal(np.log(med), AHT_SIGMA)
        return h * aht_multiplier(df.arrival_local.dt.normalize(), df.queue.values)

    legs["handle_sec"] = draw_handle(legs)
    # transfers: 4% of contacts get a second leg in another queue
    tr = legs.sample(frac=TRANSFER_SHARE * 1.12, random_state=SEED).copy()  # some are lost to abandons/closing
    targets = {q: [x for x in QUEUES if x not in (q, "outage")] for q in QUEUES}
    tr["queue"] = [targets[q][rng.integers(0, len(targets[q]))] for q in tr.queue]
    tr["leg_no"] = 2
    legs["transfer_flag"] = legs.contact_id.isin(tr.contact_id)

    def simulate_queue(df):
        """Draw waits, abandonment, and answer times for legs given the staffing cell they arrive in."""
        df = df.copy()
        df["date"] = df.arrival_local.dt.normalize()
        df["slot"] = ((df.arrival_local - df.date).dt.total_seconds() // 1800 - OPEN_HOUR * 2).astype(int).clip(0, 27)
        cnt = df.groupby(["date", "queue", "slot"]).size().rename("k").reset_index()
        cnt = cnt.merge(plan[["date", "queue", "slot", "agents_available"]], on=["date", "queue", "slot"], how="left")
        cnt["agents_available"] = cnt.agents_available.fillna(1).astype(int)
        aht = cnt.queue.map({q: 60 * AHT_MEDIAN_MIN[q] * np.exp(AHT_SIGMA ** 2 / 2) for q in QUEUES}).values
        cnt["traffic"] = cnt.k * 1.04 * aht / 1800
        cnt["pw"] = erlang_c(cnt.traffic.values, cnt.agents_available.values)
        # overloaded cells: cap the effective surplus at 0.5 agent (backlog clears into the next interval)
        cnt["rate"] = np.maximum(cnt.agents_available - cnt.traffic, 0.5) / aht
        df = df.merge(cnt[["date", "queue", "slot", "pw", "rate"]], on=["date", "queue", "slot"], how="left")
        waits = np.where(rng.random(len(df)) < df.pw.values, rng.exponential(1 / df.rate.values), 0.0)
        waits = np.minimum(waits, 1800)
        patience = rng.exponential(PATIENCE_MEAN_SEC, len(df))
        df["abandoned_flag"] = waits > patience
        df["wait_sec"] = np.where(df.abandoned_flag, patience, waits)
        return df

    legs = simulate_queue(legs)
    legs["answered_local"] = np.where(legs.abandoned_flag, pd.NaT,
                                      legs.arrival_local + pd.to_timedelta(legs.wait_sec, unit="s"))
    legs["answered_local"] = pd.to_datetime(legs.answered_local)
    # second legs start when the first leg ends (only for answered first legs)
    first_end = legs.set_index("contact_id")
    tr = tr[tr.contact_id.isin(legs.loc[~legs.abandoned_flag, "contact_id"])]
    tr["arrival_local"] = (first_end.loc[tr.contact_id, "answered_local"].values
                           + pd.to_timedelta(first_end.loc[tr.contact_id, "handle_sec"].values, unit="s"))
    tr = tr[tr.arrival_local.dt.hour < CLOSE_HOUR]
    legs.loc[~legs.contact_id.isin(tr.contact_id), "transfer_flag"] = False
    tr["handle_sec"] = draw_handle(tr)
    tr["transfer_flag"] = False
    tr = simulate_queue(tr)
    tr["answered_local"] = pd.to_datetime(np.where(tr.abandoned_flag, pd.NaT,
                                                   tr.arrival_local + pd.to_timedelta(tr.wait_sec, unit="s")))
    allg = pd.concat([legs, tr], ignore_index=True)
    allg["handle_time_sec"] = np.where(allg.abandoned_flag, 0, np.round(allg.handle_sec)).astype(int)
    allg["ended_local"] = np.where(allg.abandoned_flag,
                                   allg.arrival_local + pd.to_timedelta(allg.wait_sec, unit="s"),
                                   allg.answered_local + pd.to_timedelta(allg.handle_time_sec, unit="s"))
    allg["ended_local"] = pd.to_datetime(allg.ended_local)
    allg["reason_code"] = [REASONS[q][i % len(REASONS[q])] for q, i in
                           zip(allg.queue, rng.integers(0, 12, len(allg)))]
    allg.loc[allg.source.str.startswith("O"), "reason_code"] = "NO_INTERNET"

    # ------------------------------------------------------------- truth (clean data, before messiness)
    first = allg[allg.leg_no == 1]
    daily_true = first.groupby([first.arrival_local.dt.normalize(), "queue"]).size()
    truth_contacts = int(len(first))
    notice_aht = allg[(allg.queue.isin(NOTICE_QUEUES)) & ~allg.abandoned_flag]
    k = (notice_aht.arrival_local.dt.normalize() - NOTICE_DATE).dt.days
    in_w = notice_aht[(k >= 0) & (k < NOTICE_AHT_DAYS)].handle_sec.mean()
    pre_w = notice_aht[(k >= -28) & (k < 0)].handle_sec.mean()
    outage_calls = first[first.source.str.startswith("O")].groupby("source").size()
    o_eval = outages.set_index("outage_id").join(outage_calls.rename("calls")).fillna({"calls": 0})
    slope_realized = float((o_eval.calls * o_eval.customers_affected).sum() / (o_eval.customers_affected ** 2).sum())

    # ------------------------------------------------------------- planted messiness
    raw = allg.copy()
    # 1. missing days (ETL failure)
    raw = raw[~raw.arrival_local.dt.normalize().isin(MISSING_DAYS)]
    # 2. timestamps: UTC except before 2024-04-01 (stored as local wall time)
    local_era = raw.arrival_local < LOCAL_TS_UNTIL
    for col in ["arrival", "answered", "ended"]:
        utc = to_utc(raw[f"{col}_local"])
        raw[f"{col}_ts"] = np.where(local_era, raw[f"{col}_local"], utc)
        raw[f"{col}_ts"] = pd.to_datetime(raw[f"{col}_ts"])
    # 3. queue codes renamed at the IVR change; tech support also appears as 'TS'
    after = raw.arrival_local >= IVR_CHANGE
    raw["queue_code"] = np.where(after, raw.queue.map(NEW_CODES), raw.queue.map(OLD_CODES))
    ts_mask = after & (raw.queue == "tech_support") & (rng.random(len(raw)) < 0.15)
    raw.loc[ts_mask, "queue_code"] = "TS"
    # 4. 0.6% of abandoned legs carry a handle time
    ab = raw.abandoned_flag.values & (rng.random(len(raw)) < 0.006)
    raw.loc[ab, "handle_time_sec"] = rng.integers(5, 400, ab.sum())
    raw = raw.sort_values(["arrival_local", "leg_no"]).reset_index(drop=True)
    raw["leg_id"] = [f"L{i:07d}" for i in range(1, len(raw) + 1)]

    fmt = "%Y-%m-%d %H:%M:%S"
    out = raw[["leg_id", "contact_id", "customer_id", "queue_code", "arrival_ts", "answered_ts", "ended_ts",
               "handle_time_sec", "abandoned_flag", "transfer_flag", "reason_code"]].copy()
    for c in ["arrival_ts", "answered_ts", "ended_ts"]:
        out[c] = out[c].dt.strftime(fmt)
    out["abandoned_flag"] = out.abandoned_flag.astype(int)
    out["transfer_flag"] = out.transfer_flag.astype(int)
    out.to_csv(RAW / "fact_call_leg.csv", index=False)

    cust_out = cust.copy()
    cust_out["signup_date"] = cust_out.signup_date.dt.strftime("%Y-%m-%d")
    cust_out.to_csv(RAW / "dim_customer.csv", index=False)
    pd.DataFrame({"queue_id": range(1, 6), "queue_name": QUEUES, "sl_target": 0.80, "sl_threshold_sec": 60}
                 ).to_csv(RAW / "dim_queue.csv", index=False)
    o_out = outages.copy()
    o_out["start_ts"] = to_utc(o_out.start_local).dt.strftime(fmt)
    o_out["end_ts"] = to_utc(o_out.end_local).dt.strftime(fmt)
    o_out[["outage_id", "region", "start_ts", "end_ts", "customers_affected"]].to_csv(RAW / "fact_outage.csv", index=False)

    ev = ([(d, "holiday", "all") for d in sorted(HOLIDAYS_CLOSED.union(HOLIDAYS_OPEN))]
          + [(d, "promo", "moves_new_service") for d in PROMOS]
          + [(NOTICE_DATE, "price_notice", "billing;cancellations"), (NOTICE_2026, "price_notice", "billing;cancellations")])
    ev_df = pd.DataFrame(ev, columns=["event_date", "event_type", "queues_affected"]).sort_values("event_date")
    ev_df["is_closed"] = ev_df.event_date.isin(HOLIDAYS_CLOSED)
    ev_df["event_date"] = ev_df.event_date.dt.strftime("%Y-%m-%d")
    ev_df.to_csv(RAW / "dim_business_event.csv", index=False)

    # staffing: one row per local half-hour (48/day) per queue, including DST artifacts
    grid = pd.date_range(START, END + pd.Timedelta(hours=23, minutes=30), freq="30min")
    spring = pd.to_datetime(["2024-03-10", "2025-03-09"])
    fall = pd.to_datetime(["2024-11-03", "2025-11-02"])
    nonexistent = grid.normalize().isin(spring) & (grid.hour == 2)          # 02:00, 02:30 do not exist
    repeated = grid[grid.normalize().isin(fall) & (grid.hour == 1)]         # 01:00, 01:30 occur twice
    st = pd.DataFrame({"interval_start": grid[~nonexistent].append(repeated).sort_values()})
    st = st.loc[st.index.repeat(5)].reset_index(drop=True)
    st["queue_id"] = np.tile(np.arange(1, 6), len(st) // 5)
    st["date"] = st.interval_start.dt.normalize()
    st["slot"] = ((st.interval_start - st.date).dt.total_seconds() // 1800 - OPEN_HOUR * 2).astype(int)
    p2 = plan.assign(queue_id=plan.queue.map({q: i + 1 for i, q in enumerate(QUEUES)}))
    st = st.merge(p2[["date", "queue_id", "slot", "agents_scheduled", "agents_available"]],
                  on=["date", "queue_id", "slot"], how="left").fillna({"agents_scheduled": 0, "agents_available": 0})
    st["interval_start"] = st.interval_start.dt.strftime(fmt)
    st[["interval_start", "queue_id", "agents_scheduled", "agents_available"]].astype(
        {"agents_scheduled": int, "agents_available": int}).to_csv(RAW / "fact_staffing_interval.csv", index=False)

    dd = pd.DataFrame({"date": pd.date_range("2024-01-01", "2026-03-31", freq="D")})
    dd["dow"] = dd.date.dt.day_name().str[:3]
    dd["is_holiday"] = dd.date.isin(HOLIDAYS_CLOSED.union(HOLIDAYS_OPEN))
    dst = [pd.Timestamp(x) for x in ["2024-03-10", "2024-11-03", "2025-03-09", "2025-11-02", "2026-03-08"]]
    dd["is_dst_transition"] = dd.date.isin(dst)
    dd["date"] = dd.date.dt.strftime("%Y-%m-%d")
    dd.to_csv(RAW / "dim_date.csv", index=False)

    # Q4-2025 scheduled hours, for the roster assumption
    q4 = plan[(plan.date >= "2025-10-06") & (plan.date <= "2025-12-21")]
    weekly_sched_hours = q4.agents_scheduled.sum() * 0.5 / 11

    truth = {
        "seed": SEED,
        "parameters": {
            "dow_multipliers_raw": DOW_RAW, "dow_relative_to_thursday": DOW_RAW,
            "dow_normalized_mean1": dict(zip(DOW_RAW, DOW_NORM.round(4).tolist())),
            "intraday_peak_10_to_1130": 1.6, "intraday_peak_13_to_1430": 1.3,
            "intraday_shape": dict(zip(SLOTS, SHAPE.round(4).tolist())),
            "trend_per_month": TREND_PER_MONTH, "queue_share": QUEUE_SHARE, "base_daily_contacts": BASE_DAILY,
            "billing_cycle_lift": BILLING_LIFT, "billing_cycle_days_after_bill_date": list(BILLING_DAYS),
            "outage_calls_per_customer": OUTAGE_CALLS_PER_CUSTOMER, "outage_spread_hours": OUTAGE_SPREAD_HOURS,
            "outage_decay_hours": OUTAGE_DECAY_HOURS,
            "price_notice": {"date": str(NOTICE_DATE.date()), "lift_day0": NOTICE_LIFT,
                             "half_life_days": NOTICE_HALF_LIFE, "days": NOTICE_DAYS, "queues": list(NOTICE_QUEUES),
                             "aht_lift": NOTICE_AHT_LIFT, "aht_days": NOTICE_AHT_DAYS,
                             "scenario_2026": str(NOTICE_2026.date())},
            "aht_median_min": AHT_MEDIAN_MIN, "aht_lognormal_sigma": AHT_SIGMA,
            "holiday_open_factor": HOLIDAY_OPEN_FACTOR, "promo_lift_moves": PROMO_LIFT, "promo_days": PROMO_DAYS,
            "transfer_share": TRANSFER_SHARE, "patience_mean_sec": PATIENCE_MEAN_SEC,
            "missing_days": [str(d.date()) for d in MISSING_DAYS], "local_time_until": str(LOCAL_TS_UNTIL.date()),
            "ivr_change": str(IVR_CHANGE.date()), "abandoned_with_handle_time_share": 0.006,
        },
        "realized": {
            "contacts_total": truth_contacts, "legs_total_before_missing_days": int(len(allg)),
            "transfer_contacts": int(len(tr)), "transfer_share": len(tr) / truth_contacts,
            "outage_calls_generated": int(oc_realized_total), "outage_calls_offered": int(len(oc)),
            "outage_slope_realized": slope_realized,
            "notice_aht_ratio_realized": float(in_w / pre_w),
            "abandoned_with_handle_time": int(ab.sum()),
            "tech_ts_code_rows": int(ts_mask.sum()),
            "q4_2025_weekly_scheduled_agent_hours": float(weekly_sched_hours),
            "q4_2025_implied_fte": float(weekly_sched_hours / (40 * (1 - 0.32))),
            "abandon_rate": float(allg.abandoned_flag.mean()),
            "rows": {"fact_call_leg": int(len(out)), "dim_customer": int(len(cust_out)), "dim_queue": 5,
                     "fact_outage": int(len(outages)), "dim_business_event": int(len(ev_df)),
                     "fact_staffing_interval": int(len(st)), "dim_date": int(len(dd))},
        },
    }
    (TRUTH / "planted_effects.json").write_text(json.dumps(truth, indent=2, default=float))
    print(json.dumps(truth["realized"], indent=1, default=float))


if __name__ == "__main__":
    main()
