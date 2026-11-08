"""Static PNG charts (matplotlib) for README and docs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG, TABLES = ROOT / "figures", ROOT / "reports" / "tables"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e5e4e0"
QLABEL = {"billing": "Billing", "tech_support": "Tech support", "moves_new_service": "Moves / new service",
          "cancellations": "Cancellations", "outage": "Outage line", "total": "All queues"}


def style():
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 160, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlelocation": "left", "axes.axisbelow": True, "text.color": INK,
        "legend.frameon": False})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def daily_actuals():
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    d = con.execute("SELECT date, SUM(legs) AS legs, MAX(CAST(is_closed AS INT)) AS closed "
                    "FROM mart_daily_queue GROUP BY date ORDER BY date").df()
    con.close()
    d["date"] = pd.to_datetime(d.date)
    return d


def headline(res, act):
    fc = pd.read_csv(TABLES / "forecast_total_daily_q1_2026.csv", parse_dates=["date"])
    bt = pd.read_csv(TABLES / "backtest_forecasts.csv", parse_dates=["date", "origin"])
    last = bt[bt.origin == bt.origin.max()].groupby("date", as_index=False).regression.sum()
    a = act[act.date >= pd.Timestamp(C.HISTORY_END) - pd.Timedelta(weeks=26)].copy()
    a.loc[a.closed == 1, "legs"] = np.nan          # closed holidays shown as gaps
    last = last.copy()
    last.loc[last.regression <= 0, "regression"] = np.nan
    fc.loc[fc["mean"] <= 0, ["mean", "lo80", "hi80"]] = np.nan
    b, s = fc[fc.scenario == "baseline"], fc[fc.scenario == "price_notice"]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(a.date, a.legs, color=INK, lw=1.1, label="Actual daily calls (legs)")
    ax.plot(last.date, last.regression, color=GRAY, lw=1.3, ls="--",
            label=f"Backtest forecast from {bt.origin.max():%b %d} (13 weeks)")
    ax.fill_between(s.date, s.lo80, s.hi80, color=ORANGE, alpha=0.18, lw=0, label="Price-notice scenario, 80% PI")
    ax.plot(s.date, s["mean"], color=ORANGE, lw=1.2)
    ax.fill_between(b.date, b.lo80, b.hi80, color=BLUE, alpha=0.22, lw=0, label="Baseline forecast, 80% PI")
    ax.plot(b.date, b["mean"], color=BLUE, lw=1.4)
    ax.axvline(pd.Timestamp(C.FORECAST_START), color=INK2, lw=0.8)
    ax.text(pd.Timestamp(C.FORECAST_START) + pd.Timedelta(days=2), ax.get_ylim()[1] * 0.97, "forecast", color=INK2,
            fontsize=8.5, va="top")
    ax.annotate(f"Feb 2 price notice\n+{res['forecast']['notice_extra_legs']:,.0f} calls over 10 days",
                xy=(pd.Timestamp(C.PRICE_NOTICE_2026), res["forecast"]["scenario_peak_day_legs"]),
                xytext=(pd.Timestamp("2026-02-20"), res["forecast"]["scenario_peak_day_legs"] * 1.02),
                fontsize=8.5, color=INK2, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.annotate("2025 notice (Sep 15)", xy=(pd.Timestamp(C.PRICE_NOTICE_2025), a.set_index("date").legs.loc[C.PRICE_NOTICE_2025]),
                xytext=(pd.Timestamp("2025-08-10"), np.nanmax(a.legs) * 1.05), fontsize=8.5, color=INK2,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_ylim(0, max(np.nanmax(a.legs), np.nanmax(s.hi80)) * 1.15)
    ax.set_ylabel("Calls per day (legs, all queues)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    bt_s = res["backtest"]
    ax.set_title(f"13-week call forecast: backtest WAPE {100 * bt_s['total_wape']['regression']:.1f}% vs. "
                 f"{100 * bt_s['total_wape']['naive']:.1f}% for seasonal naive (simulated data)")
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    save(fig, "01_headline_forecast.png")


def staffing(res):
    w = pd.read_csv(TABLES / "06_staffing_requirement.csv", parse_dates=["week_start"])
    w = w[(w.week_start >= pd.Timestamp(C.FORECAST_START))
          & (w.week_start + pd.Timedelta(days=6) <= pd.Timestamp(C.FORECAST_END))]   # full weeks only
    b, s = w[w.scenario == "baseline"], w[w.scenario == "price_notice"]
    st = res["staffing"]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.fill_between(b.week_start, b.required_fte, b.required_fte_p90, color=BLUE, alpha=0.15, lw=0,
                    label="Baseline, staffed to P90 volume")
    ax.plot(b.week_start, b.required_fte, color=BLUE, lw=2, marker="o", ms=4, label="Baseline requirement")
    ax.plot(s.week_start, s.required_fte, color=ORANGE, lw=1.6, ls="--", marker="o", ms=4,
            label="With Feb 2 price notice")
    ax.axhline(C.ROSTER_FTE, color=INK, lw=1.2)
    ax.text(b.week_start.iloc[0], C.ROSTER_FTE - 0.6, f"current roster {C.ROSTER_FTE} FTE", fontsize=8.5, va="top")
    ax.axhline(C.ROSTER_FTE + st["hires_needed"], color=AQUA, lw=1.2, ls=":")
    ax.text(b.week_start.iloc[-1], C.ROSTER_FTE + st["hires_needed"] + 0.3,
            f"+{st['hires_needed']} hires (productive {st['hires_productive_from']})", fontsize=8.5, ha="right",
            color=INK2)
    ax.set_ylabel("Required FTE (after 32% shrinkage)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_title("Weekly FTE needed for 80% of calls answered in 60 s (Erlang C)")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_ylim(C.ROSTER_FTE - 6, max(b.required_fte_p90.max(), s.required_fte.max()) + 2)
    save(fig, "02_weekly_fte_vs_roster.png")


def accuracy(res):
    sc = pd.DataFrame(res["backtest"]["scores"])
    order = ["total", "tech_support", "billing", "moves_new_service", "cancellations", "outage"]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = np.arange(len(order))
    for i, (m, col, lab) in enumerate([("naive", GRAY, "Seasonal naive"), ("ets", AQUA, "Holt-Winters ETS"),
                                       ("regression", BLUE, "Regression + events, AR(1)")]):
        v = [sc[(sc.queue == q) & (sc.model == m)].wape.iloc[0] * 100 for q in order]
        ax.bar(x + (i - 1) * 0.27, v, 0.25, color=col, label=lab)
        if m == "regression":
            for xi, vi in zip(x, v):
                ax.text(xi + 0.27, vi + 0.3, f"{vi:.1f}", ha="center", fontsize=7.5, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels([QLABEL[q] for q in order])
    ax.set_ylabel("WAPE, % (8 folds x 13 weeks)")
    ax.set_title("Rolling-origin backtest: forecast error by queue and model (lower is better)")
    ax.legend(fontsize=8)
    ax.grid(axis="x", visible=False)
    save(fig, "03_backtest_accuracy.png")


def event_study(res, truth):
    w = pd.read_csv(TABLES / "price_notice_glm_counterfactual.csv")
    pn = res["price_notice"]
    k = np.arange(0, 10)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(w.k, 100 * w.excess_ratio, color=np.where(w.k.between(0, 9), BLUE, GRAY), width=0.75)
    ax.plot(k, 100 * pn["lift_day0"] * 0.5 ** (k / pn["half_life_days"]), color=INK, lw=1.6,
            label=f"Fitted: +{100 * pn['lift_day0']:.0f}% on day 0, half-life {pn['half_life_days']:.1f} days")
    p = truth["parameters"]["price_notice"]
    ax.plot(k, 100 * p["lift_day0"] * 0.5 ** (k / p["half_life_days"]), color=ORANGE, lw=1.4, ls="--",
            label=f"Planted: +{100 * p['lift_day0']:.0f}%, half-life {p['half_life_days']:.0f} days")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xlabel("Days from the 2025-09-15 price notice")
    ax.set_ylabel("Billing + cancellation contacts\nvs. counterfactual (%)")
    ax.set_title("Event study: the notice added calls for about 10 days")
    ax.legend(fontsize=8)
    save(fig, "04_price_notice_event_study.png")


def outage(res):
    o = pd.read_csv(TABLES / "03_outage_call_elasticity.csv").dropna(subset=["excess_calls_4h"])
    e = res["effects"]
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.scatter(o.customers_affected, o.excess_calls_4h, s=22, color=BLUE, alpha=0.75, edgecolor="white", lw=0.5)
    xs = np.linspace(0, o.customers_affected.max(), 50)
    ax.plot(xs, e["outage_calls_per_customer"] * xs, color=INK, lw=1.5,
            label=f"{1000 * e['outage_calls_per_customer']:.1f} calls per 1,000 customers affected")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xlabel("Customers affected by the outage")
    ax.set_ylabel("Excess tech-support calls,\nfirst 4 hours")
    ax.set_title(f"Outage call elasticity ({e['outage_n']} outages)")
    ax.legend(fontsize=8, loc="upper left")
    save(fig, "05_outage_elasticity.png")


def profile(res):
    prof = pd.read_csv(TABLES / "01_interval_volume_profile.csv")
    tot = prof.groupby(["dow", "slot48"], as_index=False).avg_legs.sum()
    fig, ax = plt.subplots(figsize=(9, 3.6))
    cols = {"Mon": BLUE, "Thu": AQUA, "Sun": ORANGE}
    for d, col in cols.items():
        t = tot[tot.dow == d]
        ax.plot(t.slot48 / 2, t.avg_legs, color=col, lw=2, label=d)
    ax.axvspan(10, 11.5, color=GRAY, alpha=0.12, lw=0)
    ax.axvspan(13, 14.5, color=GRAY, alpha=0.12, lw=0)
    e = res["effects"]
    ax.set_ylim(0, ax.get_ylim()[1])
    ax.text(10.75, 2, f"index {e['intraday_peak_10_to_1130']:.2f}", ha="center", fontsize=8.5)
    ax.text(13.75, 2, f"index {e['intraday_peak_13_to_1430']:.2f}", ha="center", fontsize=8.5)
    ax.set_xticks(range(7, 22, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(7, 22, 2)])
    ax.set_xlabel("Interval start (center local time, America/Chicago)")
    ax.set_ylabel("Average calls per 30 min")
    ax.set_title("Intraday profile: peaks at 10:00-11:30 and 13:00-14:30 (index vs. interval mean, all queues)")
    ax.legend(fontsize=8, title="Weekday", title_fontsize=8)
    save(fig, "06_intraday_profile.png")


def service_level(res):
    sl = pd.read_csv(TABLES / "05_service_level_history.csv", parse_dates=["week_start"])
    sl = sl[sl.week_start >= "2024-01-08"]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.plot(sl.week_start, 100 * sl.service_level, color=BLUE, lw=1.6, label="Service level (answered in 60 s)")
    ax.plot(sl.week_start, 100 * sl.abandon_rate, color=ORANGE, lw=1.4, label="Abandon rate")
    ax.axhline(100 * C.SL_TARGET, color=INK, lw=1, ls="--")
    ax.text(sl.week_start.iloc[2], 100 * C.SL_TARGET + 1, "target 80%", fontsize=8.5)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of calls offered")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_title("Service-level history: below target every week of 2025")
    ax.legend(fontsize=8, loc="center right")
    save(fig, "07_service_level_history.png")


def validation(res, truth):
    P, e, pn = truth["parameters"], res["effects"], res["price_notice"]
    rows = [(f"DOW index {d} vs. Thu", P["dow_relative_to_thursday"][d], e["dow_index_vs_thursday"][d],
             e["dow_index_ci"][d]) for d in ["Mon", "Tue", "Sat", "Sun"]]
    rows += [("Intraday 10:00-11:30 index", 1.6, e["intraday_peak_10_to_1130"], None),
             ("Intraday 13:00-14:30 index", 1.3, e["intraday_peak_13_to_1430"], None),
             ("Billing-cycle lift (x)", 1 + P["billing_cycle_lift"], 1 + e["billing_cycle_lift"],
              [1 + v for v in e["billing_cycle_lift_ci"]]),
             ("Price notice day-0 lift (x)", 1 + P["price_notice"]["lift_day0"], 1 + pn["lift_day0"],
              [1 + v for v in pn["lift_day0_ci"]]),
             ("Notice AHT lift (x)", 1 + P["price_notice"]["aht_lift"], 1 + pn["aht_lift"],
              [1 + v for v in pn["aht_lift_ci"]])]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for i, (lab, pl, rec, ci) in enumerate(rows[::-1]):
        if ci:
            ax.plot(ci, [i, i], color=BLUE, lw=2)
        ax.plot(rec, i, "o", color=BLUE, ms=7, mec="white", label="Recovered (95% CI)" if i == 0 else None)
        ax.plot(pl, i, "x", color=ORANGE, ms=8, mew=1.8, label="Planted" if i == 0 else None)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows[::-1]])
    ax.set_xlabel("Multiplier")
    ax.set_title("Validation: planted vs. recovered effects")
    ax.legend(fontsize=8, loc="upper left")
    save(fig, "08_validation_planted_vs_recovered.png")


def main():
    FIG.mkdir(exist_ok=True)
    style()
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    truth = json.loads((ROOT / "data" / "truth" / "planted_effects.json").read_text())
    act = daily_actuals()
    headline(res, act)
    staffing(res)
    accuracy(res)
    event_study(res, truth)
    outage(res)
    profile(res)
    service_level(res)
    validation(res, truth)
    print(f"wrote {len(list(FIG.glob('*.png')))} figures")


if __name__ == "__main__":
    main()
