"""Self-contained interactive dashboard (Plotly, JS inlined once). Writes dashboard/index.html."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "reports" / "tables"
OUT = ROOT / "dashboard" / "index.html"
BLUE, ORANGE, AQUA, GRAY, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984", "#52514e"
LAYOUT = dict(template="plotly_white", font=dict(family="Inter, Segoe UI, Arial", size=12, color="#0b0b0b"),
              margin=dict(l=60, r=30, t=70, b=50))
QLABEL = {"billing": "Billing", "tech_support": "Tech support", "moves_new_service": "Moves / new service",
          "cancellations": "Cancellations", "outage": "Outage line", "total": "All queues"}
DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def div(fig, first=False):
    return pio.to_html(fig, include_plotlyjs=True if first else False, full_html=False,
                       config={"displaylogo": False, "responsive": True})


def view_forecast(res):
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    act = con.execute("""SELECT date, queue_name, legs, is_closed FROM mart_daily_queue
                         WHERE date >= DATE '2025-07-01' ORDER BY date""").df()
    con.close()
    act["date"] = pd.to_datetime(act.date)
    act.loc[act.is_closed, "legs"] = np.nan
    fc = pd.read_csv(TABLES / "forecast_daily_q1_2026.csv", parse_dates=["date"])
    tot = pd.read_csv(TABLES / "forecast_total_daily_q1_2026.csv", parse_dates=["date"])
    tot["queue"] = "total"
    fc = pd.concat([fc, tot])
    fc.loc[fc["mean"] <= 0, ["mean", "lo80", "hi80"]] = np.nan
    a_tot = act.groupby("date", as_index=False).legs.sum(min_count=1).assign(queue_name="total")
    act = pd.concat([act, a_tot])
    queues = ["total"] + C.QUEUES
    fc[["mean", "lo80", "hi80"]] = fc[["mean", "lo80", "hi80"]].round(1)
    fig = go.Figure()
    for i, q in enumerate(queues):
        a = act[act.queue_name == q]
        vis = i == 0
        fig.add_scatter(x=a.date, y=a.legs, mode="lines", line=dict(color="#0b0b0b", width=1.2), name="Actual",
                        visible=vis, hovertemplate="%{x|%a %b %d}: %{y:,.0f}<extra>actual</extra>")
        for sc, col, nm in [("price_notice", ORANGE, "Price-notice scenario"), ("baseline", BLUE, "Baseline")]:
            f = fc[(fc.queue == q) & (fc.scenario == sc)]
            fig.add_scatter(x=pd.concat([f.date, f.date[::-1]]), y=pd.concat([f.hi80, f.lo80[::-1]]), fill="toself",
                            fillcolor=col, opacity=0.2, line=dict(width=0), name=f"{nm} 80% PI", visible=vis,
                            hoverinfo="skip")
            fig.add_scatter(x=f.date, y=f["mean"], mode="lines", line=dict(color=col, width=1.6), name=nm,
                            visible=vis, hovertemplate="%{x|%a %b %d}: %{y:,.0f}<extra>" + nm + "</extra>")
    n = len(queues) * (1 + 2 * 2)
    per = 5
    buttons = [dict(label=QLABEL[q], method="update",
                    args=[{"visible": [j // per == i for j in range(n)]}]) for i, q in enumerate(queues)]
    fig.update_layout(**LAYOUT, height=460, title="Daily calls (legs): actual, Q1-2026 baseline and price-notice scenario",
                      yaxis_title="Calls per day", legend=dict(orientation="h", y=-0.15),
                      updatemenus=[dict(buttons=buttons, type="buttons", direction="right", x=0, y=1.13, xanchor="left")])
    fig.update_layout(margin=dict(l=60, r=30, t=110, b=50))
    prof = pd.read_csv(TABLES / "01_interval_volume_profile.csv")
    f2 = go.Figure()
    for q, col in zip(C.QUEUES, [BLUE, ORANGE, AQUA, "#6250d6", GRAY]):
        p = prof[(prof.queue_name == q) & (prof.dow == "Mon")]
        f2.add_scatter(x=p.interval_label, y=p.avg_legs, mode="lines+markers", name=QLABEL[q],
                       line=dict(color=col, width=2), marker=dict(size=5),
                       hovertemplate="%{x}: %{y:.1f} calls<extra>" + QLABEL[q] + "</extra>")
    f2.update_layout(**LAYOUT, height=360, title="Interval volume by queue, average Monday (center local time)",
                     yaxis_title="Calls per 30 min", xaxis_title="Interval start")
    return [fig, f2]


def view_staffing(res):
    req = pd.read_csv(TABLES / "required_agents_heatmap.csv")
    sch = pd.read_csv(TABLES / "scheduled_agents_heatmap_q4_2025.csv")
    m = req.merge(sch, on=["dow", "slot48"], how="left")
    m["gap"] = m.agents_required - m.scheduled
    labels = [f"{s // 2:02d}:{'00' if s % 2 == 0 else '30'}" for s in sorted(m.slot48.unique())]
    figs = []
    for col, title, scale, mid in [("agents_required", "Required agents per interval, Q1-2026 baseline (Erlang C, 80/60)",
                                    [[0, "#f2f1ee"], [1, BLUE]], None),
                                   ("gap", "Required (Q1-2026) minus scheduled (Q4-2025 average) agents",
                                    [[0, BLUE], [0.5, "#f2f1ee"], [1, ORANGE]], 0)]:
        piv = m.pivot(index="dow", columns="slot48", values=col).reindex(DOWS)
        h = go.Heatmap(z=piv.values, x=labels, y=DOWS, colorscale=scale, zmid=mid,
                       hovertemplate="%{y} %{x}: %{z:.1f}<extra></extra>", colorbar=dict(title="agents"))
        f = go.Figure(h)
        f.update_layout(**LAYOUT, height=330, title=title, yaxis=dict(autorange="reversed"))
        figs.append(f)
    w = pd.read_csv(TABLES / "06_staffing_requirement.csv", parse_dates=["week_start"])
    w = w[(w.week_start >= C.FORECAST_START) & (w.week_start + pd.Timedelta(days=6) <= pd.Timestamp(C.FORECAST_END))]
    f3 = go.Figure()
    for sc, col, nm in [("baseline", BLUE, "Baseline"), ("price_notice", ORANGE, "With Feb 2 price notice")]:
        x = w[w.scenario == sc]
        f3.add_bar(x=x.week_start, y=x.fte_gap, name=nm, marker_color=col,
                   hovertemplate="week of %{x|%b %d}: %{y:+.1f} FTE<extra>" + nm + "</extra>")
    st = res["staffing"]
    f3.update_layout(**LAYOUT, height=360, barmode="group", yaxis_title=f"Required FTE minus roster ({C.ROSTER_FTE})",
                     title=f"FTE gap by week. Hire {st['hires_needed']} now (6-week training, productive "
                           f"{st['hires_productive_from']}); overtime to bridge: ${st['ot_cost_scenario']:,.0f} "
                           f"incl. ${st['ot_cost_notice_incremental']:,.0f} for the notice")
    return figs + [f3]


def view_accuracy(res):
    sc = pd.DataFrame(res["backtest"]["scores"])
    order = ["total"] + C.QUEUES
    f1 = go.Figure()
    for m, col, nm in [("naive", GRAY, "Seasonal naive"), ("ets", AQUA, "Holt-Winters ETS"),
                       ("regression", BLUE, "Regression + events")]:
        s = sc[sc.model == m].set_index("queue").loc[order]
        f1.add_bar(x=[QLABEL[q] for q in order], y=100 * s.wape, name=nm, marker_color=col,
                   customdata=s.mase, hovertemplate="%{x}: WAPE %{y:.1f}%, MASE %{customdata:.2f}<extra>" + nm + "</extra>")
    f1.update_layout(**LAYOUT, height=380, barmode="group", yaxis_title="WAPE (%)",
                     title=f"Backtest: 8 rolling origins x 13-week horizon. 80% PI coverage "
                           f"{100 * res['backtest']['pi80_coverage']:.0f}% (target 80%)")
    bt = pd.read_csv(TABLES / "backtest_forecasts.csv", parse_dates=["date", "origin"])
    t = bt.groupby(["fold", "origin", "date"], as_index=False)[["actual", "regression", "naive"]].sum()
    t["h"] = (t.date - t.origin).dt.days + 1
    t["pct_err"] = (100 * (t.actual - t.regression) / t.actual).round(2)
    f2 = go.Figure()
    f2.add_scatter(x=t.h, y=t.pct_err, mode="markers", marker=dict(size=4, color=BLUE, opacity=0.4), name="daily",
                   customdata=t.date.dt.strftime("%Y-%m-%d"),
                   hovertemplate="day %{x} (%{customdata}): %{y:.1f}%<extra></extra>")
    roll = t.groupby("h").pct_err.mean().rolling(7, center=True, min_periods=1).mean()
    f2.add_scatter(x=roll.index, y=roll.values, mode="lines", line=dict(color="#0b0b0b", width=2), name="7-day mean")
    f2.add_hline(y=0, line_color=INK2)
    f2.update_layout(**LAYOUT, height=360, title="Residual check: % error (all queues) by days ahead, regression model",
                     xaxis_title="Days ahead of forecast origin", yaxis_title="(actual - forecast) / actual, %")
    return [f1, f2]


def main():
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    views = {"Forecast": view_forecast(res), "Staffing": view_staffing(res), "Accuracy": view_accuracy(res)}
    first, sections, tabs = True, [], []
    for i, (name, figs) in enumerate(views.items()):
        html = []
        for f in figs:
            html.append(div(f, first))
            first = False
        sections.append(f'<section id="v{i}" class="view{" active" if i == 0 else ""}">{"".join(html)}</section>')
        tabs.append(f'<button class="tab{" active" if i == 0 else ""}" onclick="show({i})">{name}</button>')
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Contact-center forecast and staffing</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#fcfcfb;color:#0b0b0b}}
header{{padding:18px 28px 6px}} h1{{font-size:20px;margin:0 0 4px}} p.note{{color:#52514e;margin:0;font-size:13px}}
nav{{padding:10px 28px;border-bottom:1px solid #e5e4e0}}
.tab{{border:1px solid #d6d5d0;background:#fff;padding:7px 14px;margin-right:6px;border-radius:6px;cursor:pointer;font-size:13px}}
.tab.active{{background:#2a78d6;color:#fff;border-color:#2a78d6}}
.view{{display:none;padding:8px 28px}} .view.active{{display:block}}
</style></head><body>
<header><h1>Contact-center volume forecast and Q1-2026 staffing plan</h1>
<p class="note">All data is synthetic (seed 42): a simulated regional home-internet provider, history 2024-2025,
forecast 2026-01-01 to 2026-03-31. Service-level goal: 80% of calls answered within 60 seconds.</p></header>
<nav>{''.join(tabs)}</nav>
{''.join(sections)}
<script>
function show(i){{document.querySelectorAll('.view').forEach((v,j)=>v.classList.toggle('active',i===j));
document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',i===j));
window.dispatchEvent(new Event('resize'));}}
</script></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
