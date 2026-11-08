"""Effect recovery, forecasting with rolling-origin backtests, Erlang C staffing, and Q1-2026 sizing.

Reads data/warehouse.duckdb, runs sql/03_analysis/*.sql, writes reports/results.json and reports/tables/*.csv.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import optimize, stats
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
from erlang import agents_required  # noqa: E402

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
SQL = ROOT / "sql" / "03_analysis"
TABLES = ROOT / "reports" / "tables"
RESULTS = ROOT / "reports" / "results.json"
DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HORIZON, N_FOLDS, FOLD_STEP = 91, 8, 28
Z80 = stats.norm.ppf(0.90)


def run_sql(con, name, save=True):
    df = con.execute((SQL / name).read_text()).df()
    if save:
        df.to_csv(TABLES / name.replace(".sql", ".csv"), index=False)
    return df


# --------------------------------------------------------------------------- effect recovery
def glm_poisson(y, X):
    return sm.GLM(y, X, family=sm.families.Poisson()).fit(cov_type="HC0")


def design(feat: pd.DataFrame, queue: str | None, notice_halflife: float | None = None,
           outage_expected: float | None = None) -> pd.DataFrame:
    """Regressors for a daily model. queue=None -> total across queues."""
    X = pd.DataFrame(index=feat.index)
    X["const"] = 1.0
    X["months"] = (feat.date - pd.Timestamp(C.HISTORY_START)).dt.days / 30.4375
    for d in DOWS:
        if d != "Thu":
            X[f"dow_{d}"] = (feat.dow == d).astype(float)
    X["holiday_open"] = feat.is_holiday_open.astype(float)
    if queue in (None, "billing"):
        X["billing_cycle"] = feat.is_billing_cycle_day.astype(float)
    if queue in (None, "moves_new_service"):
        X["promo"] = feat.is_promo.astype(float)
    if queue in (None, "billing", "cancellations") and notice_halflife is not None:
        k = feat.days_since_notice
        X["notice_decay"] = np.where(k.notna(), 0.5 ** (k.fillna(0) / notice_halflife), 0.0)
    if queue in (None, "tech_support"):
        load = feat.outage_customers.astype(float) if outage_expected is None else \
            pd.Series(outage_expected, index=feat.index)
        X["outage_k_customers"] = load / 1000.0
    return X


def recover_effects(con, feat, daily, prof, outage_df, truth_shape=None):
    out = {}
    normal = feat[(~feat.is_closed) & (~feat.is_missing_data) & (feat.date <= C.HISTORY_END)].copy()
    # total contacts: DOW, trend
    tot = daily.groupby("date", as_index=False).contacts.sum()
    df = normal.merge(tot, on="date")
    df = df[df.days_since_notice.isna()]
    X = design(df, None)
    fit = glm_poisson(df.contacts.values, X)
    dow = {d: (float(np.exp(fit.params[f"dow_{d}"])) if d != "Thu" else 1.0) for d in DOWS}
    out["dow_index_vs_thursday"] = dow
    out["dow_index_ci"] = {d: [float(np.exp(fit.conf_int().loc[f"dow_{d}", 0])), float(np.exp(fit.conf_int().loc[f"dow_{d}", 1]))]
                           for d in DOWS if d != "Thu"}
    out["trend_per_month"] = float(np.exp(fit.params["months"]) - 1)
    ci = fit.conf_int().loc["months"]
    out["trend_per_month_ci"] = [float(np.exp(ci[0]) - 1), float(np.exp(ci[1]) - 1)]
    # billing cycle
    b = normal.merge(daily[daily.queue_name == "billing"][["date", "contacts"]], on="date")
    b = b[b.days_since_notice.isna()]
    fb = glm_poisson(b.contacts.values, design(b, "billing"))
    out["billing_cycle_lift"] = float(np.exp(fb.params["billing_cycle"]) - 1)
    cb = fb.conf_int().loc["billing_cycle"]
    out["billing_cycle_lift_ci"] = [float(np.exp(cb[0]) - 1), float(np.exp(cb[1]) - 1)]
    # intraday peaks: pooled across queues and weekdays (normal days)
    pooled = prof.groupby("slot48").avg_legs.sum()
    idx = pooled / pooled.mean()
    out["intraday_index"] = {f"{int(s // 2):02d}:{'00' if s % 2 == 0 else '30'}": float(v) for s, v in idx.items()}
    out["intraday_peak_10_to_1130"] = float(idx.loc[[20, 21, 22]].mean())
    out["intraday_peak_13_to_1430"] = float(idx.loc[[26, 27, 28]].mean())
    # outage elasticity: least squares through the origin, with a t-based CI
    o = outage_df.dropna(subset=["excess_calls_4h"])
    x, y = o.customers_affected.values.astype(float), o.excess_calls_4h.values
    slope = (x * y).sum() / (x * x).sum()
    resid = y - slope * x
    se = np.sqrt((resid ** 2).sum() / (len(x) - 1) / (x * x).sum())
    tq = stats.t.ppf(0.975, len(x) - 1)
    out["outage_calls_per_customer"] = float(slope)
    out["outage_calls_per_customer_ci"] = [float(slope - tq * se), float(slope + tq * se)]
    out["outage_n"] = int(len(o))
    out["outage_r2"] = float(1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum())
    return out


def price_notice_study(feat, daily):
    """Counterfactual from per-queue Poisson GLMs fitted on 2025 excluding the response window."""
    notice = pd.Timestamp(C.PRICE_NOTICE_2025)
    f = feat[(~feat.is_closed) & (~feat.is_missing_data) & (feat.date >= "2025-01-01") & (feat.date <= C.HISTORY_END)]
    rows = []
    for q in ["billing", "cancellations"]:
        d = f.merge(daily[daily.queue_name == q][["date", "contacts"]], on="date")
        k = (d.date - notice).dt.days
        train = d[~k.between(-3, 20)]
        X = design(train, q)
        fit = glm_poisson(train.contacts.values, X)
        win = d[k.between(-14, 20)].copy()
        win["cf"] = fit.predict(design(win, q)[X.columns])
        win["queue"] = q
        rows.append(win[["date", "queue", "contacts", "cf"]])
    w = pd.concat(rows).groupby("date", as_index=False)[["contacts", "cf"]].sum()
    w["k"] = (w.date - notice).dt.days
    w["excess_ratio"] = w.contacts / w.cf - 1
    fit_w = w[w.k.between(0, 9)]

    def model(k, lift, hl):
        return lift * 0.5 ** (k / hl)
    p, cov = optimize.curve_fit(model, fit_w.k.values, fit_w.excess_ratio.values, p0=[0.3, 2.0],
                                bounds=([0, 0.2], [2, 20]))
    se = np.sqrt(np.diag(cov))
    pre = w[w.k.between(-14, -1)].excess_ratio
    return w, {"lift_day0": float(p[0]), "lift_day0_ci": [float(p[0] - 1.96 * se[0]), float(p[0] + 1.96 * se[0])],
               "half_life_days": float(p[1]), "half_life_ci": [float(p[1] - 1.96 * se[1]), float(p[1] + 1.96 * se[1])],
               "excess_contacts_10d": float((fit_w.contacts - fit_w.cf).sum()),
               "pre_period_mean_abs_error": float(pre.abs().mean())}


def notice_aht(con):
    r = con.execute("""
        WITH a AS (
            SELECT arrival_date_local - DATE '2025-09-15' AS k, handle_time_sec
            FROM stg_call_leg
            WHERE queue_name IN ('billing', 'cancellations') AND NOT abandoned
        )
        SELECT AVG(CASE WHEN k BETWEEN 0 AND 13 THEN handle_time_sec END)   AS aht_window,
               AVG(CASE WHEN k BETWEEN -28 AND -1 THEN handle_time_sec END) AS aht_before,
               STDDEV(CASE WHEN k BETWEEN 0 AND 13 THEN handle_time_sec END) AS sd_w,
               COUNT(CASE WHEN k BETWEEN 0 AND 13 THEN 1 END) AS n_w,
               STDDEV(CASE WHEN k BETWEEN -28 AND -1 THEN handle_time_sec END) AS sd_b,
               COUNT(CASE WHEN k BETWEEN -28 AND -1 THEN 1 END) AS n_b
        FROM a""").df().iloc[0]
    ratio = r.aht_window / r.aht_before
    se = ratio * np.sqrt((r.sd_w / np.sqrt(r.n_w) / r.aht_window) ** 2 + (r.sd_b / np.sqrt(r.n_b) / r.aht_before) ** 2)
    return {"aht_lift": float(ratio - 1), "aht_lift_ci": [float(ratio - 1 - 1.96 * se), float(ratio - 1 + 1.96 * se)],
            "aht_before_sec": float(r.aht_before), "aht_window_sec": float(r.aht_window)}


# --------------------------------------------------------------------------- forecasting
def impute_same_dow(y: pd.Series) -> pd.Series:
    """Fill NaN with the mean of the same weekday one week before and after (for ETS / naive only)."""
    z = y.copy()
    for i in np.where(z.isna())[0]:
        vals = [y.iloc[j] for j in (i - 7, i + 7, i - 14, i + 14) if 0 <= j < len(y) and not np.isnan(y.iloc[j])]
        z.iloc[i] = np.mean(vals[:2]) if vals else np.nanmean(y)
    return z


def fit_forecast_sarimax(y_train, X_train, X_future):
    keep = [c for c in X_train.columns if X_train[c].abs().sum() > 0]
    mod = SARIMAX(np.log(y_train.values), exog=X_train[keep].values, order=(1, 0, 0), trend="n")
    res = mod.fit(disp=False, maxiter=200)
    fc = res.get_forecast(steps=len(X_future), exog=X_future[keep].values)
    mean_log, se_log = fc.predicted_mean, np.sqrt(fc.var_pred_mean)
    sigma2 = res.params[-1]
    return np.exp(mean_log + 0.5 * sigma2), np.exp(mean_log - Z80 * se_log), np.exp(mean_log + Z80 * se_log), res, keep


def forecast_models(y, feat, queue, origin_idx, horizon, halflife, notice_in_future=True):
    """Fit three models on y[:origin_idx] and forecast horizon days. y: Series with NaN on closed/missing."""
    train = y.iloc[:origin_idx]
    fut = feat.iloc[origin_idx:origin_idx + horizon]
    tr_feat = feat.iloc[:origin_idx]
    out_exp = float(tr_feat.outage_customers[~tr_feat.is_closed].mean())
    X_tr = design(tr_feat, queue, halflife)
    X_fu = design(fut, queue, halflife, outage_expected=out_exp)
    if not notice_in_future and "notice_decay" in X_fu:
        X_fu["notice_decay"] = 0.0
    closed = fut.is_closed.values
    # seasonal naive: repeat the last observed week
    yi = impute_same_dow(train)
    last_week = yi.iloc[-7:].values
    naive = np.array([last_week[i % 7] for i in range(len(fut))])
    # ETS (Holt-Winters, damped additive trend, multiplicative weekly seasonality)
    ets = ExponentialSmoothing(yi.values, trend="add", damped_trend=True, seasonal="mul",
                               seasonal_periods=7).fit(optimized=True)
    ets_fc = ets.forecast(len(fut))
    # regression with event regressors and AR(1) errors
    reg, lo, hi, res, keep = fit_forecast_sarimax(train, X_tr, X_fu)
    fc = pd.DataFrame({"date": fut.date.values, "naive": naive, "ets": ets_fc, "regression": reg,
                       "reg_lo80": lo, "reg_hi80": hi})
    fc.loc[closed, ["naive", "ets", "regression", "reg_lo80", "reg_hi80"]] = 0.0
    scale = np.nanmean(np.abs(yi.values[7:] - yi.values[:-7]))  # in-sample seasonal-naive MAE (MASE scale)
    return fc, scale, res, keep


def backtest(feat, series, halflife):
    feat_h = feat[feat.date <= C.HISTORY_END].reset_index(drop=True)
    n = len(feat_h)
    origins = [n - HORIZON - FOLD_STEP * (N_FOLDS - 1 - k) for k in range(N_FOLDS)]
    rows, total_scale = [], {}
    for k, o in enumerate(origins):
        tot = sum(impute_same_dow(y.iloc[:o]) for y in series.values())
        total_scale[k + 1] = float(np.nanmean(np.abs(tot.values[7:] - tot.values[:-7])))
        for q, y in series.items():
            fc, scale, _, _ = forecast_models(y, feat_h, q, o, HORIZON, halflife)
            fc["actual"] = y.iloc[o:o + HORIZON].values
            fc["queue"], fc["fold"], fc["origin"], fc["scale"] = q, k + 1, feat_h.date.iloc[o], scale
            rows.append(fc)
    bt = pd.concat(rows, ignore_index=True)
    bt = bt[bt.actual.notna() & (bt.actual > 0)]
    bt.attrs["total_scale"] = total_scale
    return bt


def score(bt):
    recs = []
    for (q,), g in list(bt.groupby(["queue"])) + [(("total",), None)]:
        if q == "total":
            g = bt.groupby(["fold", "date"], as_index=False)[["actual", "naive", "ets", "regression"]].sum()
            g["scale"] = g.fold.map(bt.attrs["total_scale"])
        for m in ["naive", "ets", "regression"]:
            err = (g.actual - g[m]).abs()
            wape = err.sum() / g.actual.sum()
            mase = (g.assign(e=err).groupby("fold").apply(lambda x: x.e.mean() / x.scale.iloc[0])).mean()
            recs.append({"queue": q, "model": m, "wape": float(wape), "mase": float(mase)})
    s = pd.DataFrame(recs)
    cov = bt.assign(inside=(bt.actual >= bt.reg_lo80) & (bt.actual <= bt.reg_hi80)).inside.mean()
    return s, float(cov)


# --------------------------------------------------------------------------- staffing
def interval_requirements(con, fc_daily, prof, aht_q, aht_lift, notice_date):
    share = prof[["queue_name", "dow", "slot48", "share_of_day_last_26w"]]
    rows = []
    for sc, g in fc_daily.groupby("scenario"):
        g = g.copy()
        g["dow"] = g.date.dt.day_name().str[:3]
        m = g.merge(share, left_on=["queue", "dow"], right_on=["queue_name", "dow"])
        m["calls"] = m["mean"] * m.share_of_day_last_26w
        m["calls_p90"] = m["hi80"] * m.share_of_day_last_26w
        aht = m.queue.map(aht_q).values.astype(float)
        if sc == "price_notice":
            k = (m.date - notice_date).dt.days
            aht = np.where(m.queue.isin(["billing", "cancellations"]) & k.between(0, 13), aht * (1 + aht_lift), aht)
        m["aht_sec"] = aht
        m["agents_required"] = agents_required(m.calls.values, aht, sl_target=C.SL_TARGET, target_sec=C.SL_SECONDS)
        m["agents_required_p90"] = agents_required(m.calls_p90.values, aht, sl_target=C.SL_TARGET,
                                                   target_sec=C.SL_SECONDS)
        m["scenario"] = sc
        rows.append(m[["scenario", "date", "queue", "slot48", "calls", "calls_p90", "aht_sec", "agents_required",
                       "agents_required_p90"]].rename(columns={"calls": "forecast_legs"}))
    out = pd.concat(rows, ignore_index=True)
    # pooled alternative: one cross-trained team answers all queues
    pooled = out.groupby(["scenario", "date", "slot48"], as_index=False).apply(
        lambda x: pd.Series({"calls": x.forecast_legs.sum(),
                             "aht": (x.forecast_legs * x.aht_sec).sum() / max(x.forecast_legs.sum(), 1e-9)}),
        include_groups=False)
    pooled["agents_pooled"] = agents_required(pooled.calls.values, pooled.aht.values,
                                              sl_target=C.SL_TARGET, target_sec=C.SL_SECONDS)
    return out, pooled


def sizing(weekly: pd.DataFrame, pooled_weekly: pd.DataFrame) -> dict:
    hpf = C.HOURS_PER_FTE_WEEK * (1 - C.SHRINKAGE)   # productive hours per FTE-week
    base = weekly[weekly.scenario == "baseline"].set_index("week_start")
    scen = weekly[weekly.scenario == "price_notice"].set_index("week_start")
    plan_start = pd.Timestamp(C.FORECAST_START)
    full_weeks = base.index[(base.index >= plan_start) & (base.index + pd.Timedelta(days=6) <= pd.Timestamp(C.FORECAST_END))]
    gap_weeks = base.loc[full_weeks][base.loc[full_weeks].required_fte > C.ROSTER_FTE]
    need_week = gap_weeks.index.min() if len(gap_weeks) else None
    # permanent hires: cover the highest baseline full-week requirement in the quarter
    peak_base = float(base.loc[full_weeks].required_fte.max())
    hires = int(np.ceil(max(peak_base - C.ROSTER_FTE, 0)))
    if need_week is not None:
        hire_by = need_week - pd.Timedelta(weeks=C.TRAINING_WEEKS)
        ready = max(need_week, plan_start + pd.Timedelta(weeks=C.TRAINING_WEEKS))
    else:
        hire_by, ready = None, None

    def ot(frame):
        ready_fte = np.where((ready is not None) & (frame.index >= (ready or plan_start)), C.ROSTER_FTE + hires, C.ROSTER_FTE)
        hours = np.maximum(frame.productive_agent_hours.values - ready_fte * hpf, 0)
        return pd.Series(hours, index=frame.index)
    ot_base, ot_scen = ot(base), ot(scen)
    ot_none_base = np.maximum(base.productive_agent_hours - C.ROSTER_FTE * hpf, 0)
    ot_none_scen = np.maximum(scen.productive_agent_hours - C.ROSTER_FTE * hpf, 0)
    notice_weeks = scen.index[(scen.required_fte - base.required_fte) > 0.05]
    pw = pooled_weekly.set_index(["scenario", "week_start"])
    pooled_base = pw.loc["baseline"].loc[full_weeks]
    return {
        "roster_fte": C.ROSTER_FTE, "shrinkage": C.SHRINKAGE, "training_weeks": C.TRAINING_WEEKS,
        "ot_rate": C.OT_RATE,
        "baseline_required_fte_mean": float(base.loc[full_weeks].required_fte.mean()),
        "baseline_required_fte_peak": peak_base,
        "baseline_required_fte_first_week": float(base.loc[full_weeks].required_fte.iloc[0]),
        "baseline_required_fte_last_week": float(base.loc[full_weeks].required_fte.iloc[-1]),
        "baseline_required_fte_p90_peak": float(base.loc[full_weeks].required_fte_p90.max()),
        "scenario_required_fte_peak": float(scen.loc[full_weeks].required_fte.max()),
        "scenario_peak_week": str(scen.loc[full_weeks].required_fte.idxmax().date()),
        "notice_weeks": [str(w.date()) for w in notice_weeks],
        "notice_extra_fte_peak": float((scen.required_fte - base.required_fte).max()),
        "weeks_over_roster_baseline": int(len(gap_weeks)), "full_weeks": int(len(full_weeks)),
        "first_gap_week": str(need_week.date()) if need_week is not None else None,
        "hires_needed": hires,
        "hire_by_date": str(hire_by.date()) if hire_by is not None else None,
        "hire_by_already_passed": bool(hire_by is not None and hire_by < plan_start),
        "hires_productive_from": str(ready.date()) if ready is not None else None,
        "ot_hours_baseline": float(ot_base.sum()), "ot_hours_scenario": float(ot_scen.sum()),
        "ot_cost_baseline": float(ot_base.sum() * C.OT_RATE), "ot_cost_scenario": float(ot_scen.sum() * C.OT_RATE),
        "ot_cost_notice_incremental": float((ot_scen.sum() - ot_base.sum()) * C.OT_RATE),
        "ot_hours_notice_incremental": float(ot_scen.sum() - ot_base.sum()),
        "ot_cost_no_hiring_baseline": float(ot_none_base.sum() * C.OT_RATE),
        "ot_cost_no_hiring_scenario": float(ot_none_scen.sum() * C.OT_RATE),
        "pooled_required_fte_mean": float(pooled_base.required_fte.mean()),
        "pooled_saving_fte": float(base.loc[full_weeks].required_fte.mean() - pooled_base.required_fte.mean()),
    }


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    res: dict = {}
    feat = con.execute("SELECT * FROM mart_daily_features ORDER BY date").df()
    feat["date"] = pd.to_datetime(feat.date)
    daily = con.execute("SELECT * FROM mart_daily_queue ORDER BY date, queue_name").df()
    daily["date"] = pd.to_datetime(daily.date)

    prof = run_sql(con, "01_interval_volume_profile.sql")
    bill = run_sql(con, "02_billing_cycle_effect.sql")
    outage = run_sql(con, "03_outage_call_elasticity.sql")
    ev = run_sql(con, "04_price_notice_event_study.sql")
    sl = run_sql(con, "05_service_level_history.sql")

    res["effects"] = recover_effects(con, feat, daily, prof, outage)
    res["effects"]["billing_cycle_lift_sql_by_year"] = bill[bill.dow.str.startswith("ALL")][["yr", "lift"]].to_dict("records")
    w, notice = price_notice_study(feat, daily)
    w.to_csv(TABLES / "price_notice_glm_counterfactual.csv", index=False)
    notice.update(notice_aht(con))
    res["price_notice"] = notice
    halflife = notice["half_life_days"]

    # contacts vs. legs
    cl = con.execute("""SELECT COUNT(*) AS contacts, SUM(CASE WHEN n_legs > 1 THEN 1 ELSE 0 END) AS multi,
                               (SELECT COUNT(*) FROM stg_call_leg) AS legs FROM fct_contact""").df().iloc[0]
    res["contacts_vs_legs"] = {"contacts": int(cl.contacts), "legs": int(cl.legs),
                               "multi_leg_share": float(cl.multi / cl.contacts)}

    # service-level history
    sl2 = sl[sl.week_start >= pd.Timestamp("2024-01-08")]
    res["service_level"] = {
        "sl_2024": float(sl2[sl2.week_start.dt.year == 2024].pipe(lambda x: (x.service_level * x.legs).sum() / x.legs.sum())),
        "sl_2025": float(sl2[sl2.week_start.dt.year == 2025].pipe(lambda x: (x.service_level * x.legs).sum() / x.legs.sum())),
        "sl_q4_2025": float(sl2[sl2.week_start >= pd.Timestamp("2025-10-01")].pipe(
            lambda x: (x.service_level * x.legs).sum() / x.legs.sum())),
        "abandon_2025": float(sl2[sl2.week_start.dt.year == 2025].pipe(lambda x: (x.abandon_rate * x.legs).sum() / x.legs.sum())),
        "weeks_meeting_target_2025": int((sl2[sl2.week_start.dt.year == 2025].service_level >= C.SL_TARGET).sum()),
        "weeks_2025": int((sl2.week_start.dt.year == 2025).sum()),
        "notice_week_sl": float(sl[sl.week_start == pd.Timestamp("2025-09-15")].service_level.iloc[0]),
        "occupancy_2025": float(sl2[sl2.week_start.dt.year == 2025].occupancy.mean()),
    }

    # ------------------------------------------------------------------ backtest
    hist = feat[feat.date <= C.HISTORY_END].reset_index(drop=True)
    series = {}
    for q in C.QUEUES:
        s = daily[daily.queue_name == q].set_index("date").legs.reindex(hist.date)
        s[hist.is_closed.values] = np.nan
        s = s.astype(float).reset_index(drop=True)
        s[s <= 0] = np.nan
        series[q] = s
    bt = backtest(feat, series, halflife)
    bt.to_csv(TABLES / "backtest_forecasts.csv", index=False)
    scores, coverage = score(bt)
    scores.to_csv(TABLES / "backtest_scores.csv", index=False)
    res["backtest"] = {"folds": N_FOLDS, "horizon_days": HORIZON, "fold_step_days": FOLD_STEP,
                       "origins": sorted({str(d.date()) for d in bt.origin}),
                       "scores": scores.to_dict("records"), "pi80_coverage": coverage}
    tot = scores[scores.queue == "total"].set_index("model")
    res["backtest"]["total_wape"] = tot.wape.to_dict()
    res["backtest"]["total_mase"] = tot.mase.to_dict()
    res["backtest"]["wape_reduction_vs_naive"] = float(1 - tot.loc["regression", "wape"] / tot.loc["naive", "wape"])
    best = tot.wape.idxmin()
    res["backtest"]["best_model"] = best

    # ------------------------------------------------------------------ final forecast Q1 2026
    full = feat[feat.date <= C.FORECAST_END].reset_index(drop=True)
    origin = int((full.date <= C.HISTORY_END).sum())
    h = len(full) - origin
    fc_rows, coefs = [], {}
    for q in C.QUEUES:
        y = pd.concat([series[q], pd.Series([np.nan] * h)], ignore_index=True)
        for sc, flag in [("baseline", False), ("price_notice", True)]:
            fc, _, rmod, keep = forecast_models(y, full, q, origin, h, halflife, notice_in_future=flag)
            fc_rows.append(pd.DataFrame({"date": fc.date, "queue": q, "scenario": sc, "mean": fc.regression,
                                         "lo80": fc.reg_lo80, "hi80": fc.reg_hi80}))
            if sc == "baseline":
                coefs[q] = dict(zip(keep, np.round(rmod.params[:len(keep)], 4).tolist()))
    fc_daily = pd.concat(fc_rows, ignore_index=True)
    fc_daily["date"] = pd.to_datetime(fc_daily.date)
    fc_daily.to_csv(TABLES / "forecast_daily_q1_2026.csv", index=False)
    res["forecast_coefficients_log_scale"] = coefs
    agg = fc_daily.groupby("scenario")["mean"].sum()
    res["forecast"] = {"q1_legs_baseline": float(agg["baseline"]), "q1_legs_scenario": float(agg["price_notice"]),
                       "notice_extra_legs": float(agg["price_notice"] - agg["baseline"]),
                       "q4_2025_legs": float(daily[(daily.date >= "2025-10-01")].legs.sum()),
                       "q1_2025_legs": float(daily[(daily.date >= "2025-01-01") & (daily.date <= "2025-03-31")].legs.sum())}
    res["forecast"]["growth_vs_q1_2025"] = res["forecast"]["q1_legs_baseline"] / res["forecast"]["q1_2025_legs"] - 1
    # total across queues; PI combined assuming independent queue errors (variance of each from PI width)
    fc_daily["var"] = ((fc_daily.hi80 - fc_daily.lo80) / (2 * Z80)) ** 2
    tot_day = fc_daily.groupby(["scenario", "date"], as_index=False)[["mean", "var"]].sum()
    tot_day["lo80"] = np.maximum(tot_day["mean"] - Z80 * np.sqrt(tot_day["var"]), 0)
    tot_day["hi80"] = tot_day["mean"] + Z80 * np.sqrt(tot_day["var"])
    tot_day.drop(columns="var").to_csv(TABLES / "forecast_total_daily_q1_2026.csv", index=False)
    fc_daily = fc_daily.drop(columns="var")
    peak = tot_day[tot_day.scenario == "price_notice"].sort_values("mean").iloc[-1]
    res["forecast"]["scenario_peak_day"] = str(peak.date.date())
    res["forecast"]["scenario_peak_day_legs"] = float(peak["mean"])

    # ------------------------------------------------------------------ staffing
    aht_q = con.execute("""SELECT queue_name, AVG(handle_time_sec) AS aht FROM stg_call_leg
                           WHERE NOT abandoned AND arrival_date_local BETWEEN DATE '2025-10-01' AND DATE '2025-12-31'
                           GROUP BY queue_name""").df().set_index("queue_name").aht.to_dict()
    res["aht_q4_2025_sec"] = aht_q
    ia, pooled = interval_requirements(con, fc_daily, prof, aht_q, notice["aht_lift"], pd.Timestamp(C.PRICE_NOTICE_2026))
    con.execute("DROP TABLE IF EXISTS fcst_interval_agents")
    con.register("ia_df", ia)
    con.execute("CREATE TABLE fcst_interval_agents AS SELECT * FROM ia_df")
    con.unregister("ia_df")
    weekly = run_sql(con, "06_staffing_requirement.sql")
    pooled["week_start"] = pooled.date - pd.to_timedelta(pooled.date.dt.dayofweek, unit="D")
    pw = pooled.groupby(["scenario", "week_start"], as_index=False).agents_pooled.sum()
    pw["required_fte"] = pw.agents_pooled * 0.5 / (1 - C.SHRINKAGE) / C.HOURS_PER_FTE_WEEK
    pw.to_csv(TABLES / "pooled_staffing_weekly.csv", index=False)
    weekly["week_start"] = pd.to_datetime(weekly.week_start)
    res["staffing"] = sizing(weekly, pw)
    # heatmap input for the dashboard: average required agents by weekday x interval (baseline, all queues)
    hm = ia[ia.scenario == "baseline"].groupby(["date", "slot48"], as_index=False).agents_required.sum()
    hm["dow"] = pd.to_datetime(hm.date).dt.day_name().str[:3]
    hm.groupby(["dow", "slot48"], as_index=False).agents_required.mean().to_csv(TABLES / "required_agents_heatmap.csv", index=False)
    sched = con.execute("""SELECT dayname(date) AS dow_name, slot48, AVG(agents_scheduled) AS scheduled FROM (
                               SELECT date, slot48, SUM(agents_scheduled) AS agents_scheduled FROM mart_interval_queue
                               WHERE date >= DATE '2025-10-01' AND slot48 BETWEEN 14 AND 41 GROUP BY date, slot48)
                           GROUP BY 1, 2 ORDER BY 1, 2""").df()
    sched["dow"] = sched.dow_name.str[:3]
    sched[["dow", "slot48", "scheduled"]].to_csv(TABLES / "scheduled_agents_heatmap_q4_2025.csv", index=False)

    # ------------------------------------------------------------------ data quality summary
    dq = con.execute("""
        SELECT
          (SELECT COUNT(*) FROM raw_fact_call_leg)                                       AS legs,
          (SELECT SUM(CAST(tz_fixed_flag AS INT)) FROM stg_call_leg)                     AS tz_fixed_rows,
          (SELECT COUNT(DISTINCT queue_code_raw) FROM stg_call_leg)                      AS raw_queue_codes,
          (SELECT SUM(CASE WHEN queue_code_raw = 'TS' THEN 1 ELSE 0 END) FROM stg_call_leg) AS ts_rows,
          (SELECT SUM(CASE WHEN queue_name IS NULL THEN 1 ELSE 0 END) FROM stg_call_leg) AS unmapped_codes,
          (SELECT SUM(CAST(handle_time_fixed_flag AS INT)) FROM stg_call_leg)            AS abandoned_handle_fixed,
          (SELECT SUM(CASE WHEN abandoned THEN 1 ELSE 0 END) FROM stg_call_leg)          AS abandoned_legs,
          (SELECT SUM(CAST(is_missing_data AS INT)) FROM mart_daily_features)            AS missing_days,
          (SELECT COUNT(*) FROM raw_fact_staffing_interval)                              AS staffing_rows_raw,
          (SELECT SUM(source_rows - 1) FROM stg_staffing_interval)                       AS dst_duplicate_rows
    """).df().iloc[0]
    res["data_quality"] = {k: int(v) for k, v in dq.items()}
    res["data_quality"]["missing_dates"] = [str(d.date()) for d in feat[feat.is_missing_data].date]
    # if the pre-migration rows were (wrongly) read as UTC and converted to local, how many land outside 07-21?
    naive_q1 = con.execute("""SELECT COUNT(*) FROM (
                                  SELECT EXTRACT(hour FROM (arrival_ts AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago') AS h
                                  FROM raw_fact_call_leg WHERE arrival_ts < TIMESTAMP '2024-04-01')
                              WHERE h < 7 OR h >= 21""").fetchone()[0]
    res["data_quality"]["q1_2024_calls_outside_hours_if_read_as_utc"] = int(naive_q1)

    RESULTS.write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    e = res["effects"]
    print(f"DOW Mon {e['dow_index_vs_thursday']['Mon']:.3f} trend {e['trend_per_month']:.4f} billing {e['billing_cycle_lift']:.3f} "
          f"outage {e['outage_calls_per_customer']:.4f} notice {notice['lift_day0']:.3f}/{notice['half_life_days']:.2f}d aht {notice['aht_lift']:.3f}")
    print(f"peaks {e['intraday_peak_10_to_1130']:.3f} {e['intraday_peak_13_to_1430']:.3f}")
    print(scores[scores.queue == "total"], f"coverage {coverage:.3f}")
    print(json.dumps(res["staffing"], indent=1))


if __name__ == "__main__":
    main()
