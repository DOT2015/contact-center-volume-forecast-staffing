"""Fill README.md and docs/executive_summary.md from reports/results.json and the truth file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "docs" / "templates"


def pct(x, d=1):
    return f"{100 * x:.{d}f}"


def money(x):
    return f"${x:,.0f}"


def inside(v, lo, hi):
    return "yes" if lo <= v <= hi else "no"


def build_context(res, truth):
    P, T = truth["parameters"], truth["realized"]
    e, pn, st, bt = res["effects"], res["price_notice"], res["staffing"], res["backtest"]
    sc = pd.DataFrame(bt["scores"])
    dq, sl, fc = res["data_quality"], res["service_level"], res["forecast"]
    tw, tm = bt["total_wape"], bt["total_mase"]
    c = {
        "wape_reg": pct(tw["regression"]), "wape_ets": pct(tw["ets"]), "wape_naive": pct(tw["naive"]),
        "mase_reg": f"{tm['regression']:.2f}", "mase_ets": f"{tm['ets']:.2f}", "mase_naive": f"{tm['naive']:.2f}",
        "wape_cut": f"{100 * bt['wape_reduction_vs_naive']:.0f}", "pi_cov": f"{100 * bt['pi80_coverage']:.0f}",
        "first_origin": bt["origins"][0], "last_origin": bt["origins"][-1],
        "q1_base": f"{fc['q1_legs_baseline']:,.0f}", "q1_scen": f"{fc['q1_legs_scenario']:,.0f}",
        "notice_extra": f"{fc['notice_extra_legs']:,.0f}", "growth": pct(fc["growth_vs_q1_2025"]),
        "peak_day": fc["scenario_peak_day"], "peak_day_legs": f"{fc['scenario_peak_day_legs']:,.0f}",
        "roster": str(C.ROSTER_FTE), "req_mean": f"{st['baseline_required_fte_mean']:.1f}",
        "req_peak": f"{st['baseline_required_fte_peak']:.1f}", "req_first": f"{st['baseline_required_fte_first_week']:.1f}",
        "req_p90": f"{st['baseline_required_fte_p90_peak']:.1f}",
        "scen_peak": f"{st['scenario_required_fte_peak']:.1f}", "scen_peak_week": st["scenario_peak_week"],
        "notice_fte": f"{st['notice_extra_fte_peak']:.1f}",
        "gap_weeks": str(st["weeks_over_roster_baseline"]), "full_weeks": str(st["full_weeks"]),
        "first_gap": st["first_gap_week"] or "none", "hires": str(st["hires_needed"]),
        "hire_by": st["hire_by_date"] or "n/a", "ready": st["hires_productive_from"] or "n/a",
        "ot_base": money(st["ot_cost_baseline"]), "ot_scen": money(st["ot_cost_scenario"]),
        "ot_notice": money(st["ot_cost_notice_incremental"]), "ot_notice_h": f"{st['ot_hours_notice_incremental']:,.0f}",
        "ot_h_scen": f"{st['ot_hours_scenario']:,.0f}",
        "ot_nohire_base": money(st["ot_cost_no_hiring_baseline"]), "ot_nohire_scen": money(st["ot_cost_no_hiring_scenario"]),
        "pooled_fte": f"{st['pooled_required_fte_mean']:.1f}", "pooled_save": f"{st['pooled_saving_fte']:.1f}",
        "sl_2024": pct(sl["sl_2024"]), "sl_2025": pct(sl["sl_2025"]), "sl_q4": pct(sl["sl_q4_2025"]),
        "ab_2025": pct(sl["abandon_2025"]), "sl_weeks_ok": str(sl["weeks_meeting_target_2025"]),
        "sl_weeks": str(sl["weeks_2025"]), "sl_notice": pct(sl["notice_week_sl"]), "occ": pct(sl["occupancy_2025"], 0),
        "contacts": f"{res['contacts_vs_legs']['contacts']:,}", "legs": f"{res['contacts_vs_legs']['legs']:,}",
        "multi": pct(res["contacts_vs_legs"]["multi_leg_share"]),
        "mon": f"{e['dow_index_vs_thursday']['Mon']:.2f}", "sun": f"{e['dow_index_vs_thursday']['Sun']:.2f}",
        "trend": f"{100 * e['trend_per_month']:.2f}", "bill": pct(e["billing_cycle_lift"]),
        "bill_lo": pct(e["billing_cycle_lift_ci"][0]), "bill_hi": pct(e["billing_cycle_lift_ci"][1]),
        "outage_k": f"{1000 * e['outage_calls_per_customer']:.1f}",
        "outage_lo": f"{1000 * e['outage_calls_per_customer_ci'][0]:.1f}",
        "outage_hi": f"{1000 * e['outage_calls_per_customer_ci'][1]:.1f}", "outage_n": str(e["outage_n"]),
        "pn_lift": pct(pn["lift_day0"], 0), "pn_lo": pct(pn["lift_day0_ci"][0], 0), "pn_hi": pct(pn["lift_day0_ci"][1], 0),
        "pn_hl": f"{pn['half_life_days']:.1f}", "pn_hl_lo": f"{pn['half_life_ci'][0]:.1f}",
        "pn_hl_hi": f"{pn['half_life_ci'][1]:.1f}", "pn_excess": f"{pn['excess_contacts_10d']:,.0f}",
        "aht_lift": pct(pn["aht_lift"]), "peak1": f"{e['intraday_peak_10_to_1130']:.2f}",
        "peak2": f"{e['intraday_peak_13_to_1430']:.2f}",
        "dq_legs": f"{dq['legs']:,}", "dq_tz": f"{dq['tz_fixed_rows']:,}",
        "dq_tz_bad": f"{dq['q1_2024_calls_outside_hours_if_read_as_utc']:,}",
        "dq_codes": str(dq["raw_queue_codes"]), "dq_ts": f"{dq['ts_rows']:,}", "dq_unmapped": str(dq["unmapped_codes"]),
        "dq_ab": f"{dq['abandoned_handle_fixed']:,}", "dq_ab_pct": pct(dq["abandoned_handle_fixed"] / dq["abandoned_legs"]),
        "dq_missing": ", ".join(dq["missing_dates"]), "dq_dst": str(dq["dst_duplicate_rows"]),
        "dq_staff": f"{dq['staffing_rows_raw']:,}",
        "aht_bill": f"{res['aht_q4_2025_sec']['billing'] / 60:.1f}", "aht_tech": f"{res['aht_q4_2025_sec']['tech_support'] / 60:.1f}",
        "n_rows_legs": f"{T['rows']['fact_call_leg']:,}", "n_rows_staff": f"{T['rows']['fact_staffing_interval']:,}",
    }
    best = sc[(sc.model == "regression") & (sc.queue != "total")].sort_values("wape")
    c["best_queue"], c["best_queue_wape"] = best.queue.iloc[0].replace("_", " "), pct(best.wape.iloc[0])
    c["worst_queue"], c["worst_queue_wape"] = best.queue.iloc[-1].replace("_", " "), pct(best.wape.iloc[-1])
    # validation table
    rows = []
    for d in ["Mon", "Tue", "Wed", "Fri", "Sat", "Sun"]:
        lo, hi = e["dow_index_ci"][d]
        rows.append(f"| Day-of-week index, {d} vs. Thu | {P['dow_relative_to_thursday'][d]:.2f} | - | "
                    f"{e['dow_index_vs_thursday'][d]:.3f} ({lo:.3f} to {hi:.3f}) | {inside(P['dow_relative_to_thursday'][d], lo, hi)} |")
    rows.append(f"| Intraday index 10:00-11:30 | 1.60 | - | {e['intraday_peak_10_to_1130']:.3f} | "
                f"{'yes' if abs(e['intraday_peak_10_to_1130'] - 1.6) < 0.03 else 'no'} (within 0.03) |")
    rows.append(f"| Intraday index 13:00-14:30 | 1.30 | - | {e['intraday_peak_13_to_1430']:.3f} | "
                f"{'yes' if abs(e['intraday_peak_13_to_1430'] - 1.3) < 0.03 else 'no'} (within 0.03) |")
    tlo, thi = e["trend_per_month_ci"]
    rows.append(f"| Trend per month | {100 * P['trend_per_month']:.2f}% | - | {100 * e['trend_per_month']:.2f}% "
                f"({100 * tlo:.2f}% to {100 * thi:.2f}%) | {inside(P['trend_per_month'], tlo, thi)} |")
    blo, bhi = e["billing_cycle_lift_ci"]
    rows.append(f"| Billing-cycle lift, days 1-3 after bill date | {pct(P['billing_cycle_lift'])}% | - | {c['bill']}% "
                f"({c['bill_lo']}% to {c['bill_hi']}%) | {inside(P['billing_cycle_lift'], blo, bhi)} |")
    olo, ohi = e["outage_calls_per_customer_ci"]
    rows.append(f"| Outage calls per affected customer | {P['outage_calls_per_customer']:.4f} | {T['outage_slope_realized']:.4f} | "
                f"{e['outage_calls_per_customer']:.4f} ({olo:.4f} to {ohi:.4f}) | "
                f"{inside(T['outage_slope_realized'], olo, ohi)} |")
    llo, lhi = pn["lift_day0_ci"]
    rows.append(f"| Price-notice lift, day 0 | {pct(P['price_notice']['lift_day0'], 0)}% | - | {c['pn_lift']}% "
                f"({c['pn_lo']}% to {c['pn_hi']}%) | {inside(P['price_notice']['lift_day0'], llo, lhi)} |")
    hlo, hhi = pn["half_life_ci"]
    rows.append(f"| Price-notice half-life (days) | {P['price_notice']['half_life_days']:.1f} | - | {c['pn_hl']} "
                f"({c['pn_hl_lo']} to {c['pn_hl_hi']}) | {inside(P['price_notice']['half_life_days'], hlo, hhi)} |")
    alo, ahi = pn["aht_lift_ci"]
    rows.append(f"| Price-notice AHT lift (14 days) | {pct(P['price_notice']['aht_lift'], 0)}% | {pct(T['notice_aht_ratio_realized'] - 1)}% | "
                f"{c['aht_lift']}% ({pct(alo)}% to {pct(ahi)}%) | {inside(T['notice_aht_ratio_realized'] - 1, alo, ahi)} |")
    rows.append(f"| Contacts split into 2 legs by transfer | {pct(P['transfer_share'], 0)}% | {pct(T['transfer_share'])}% | "
                f"{c['multi']}% | {'yes' if abs(T['transfer_share'] - res['contacts_vs_legs']['multi_leg_share']) < 0.002 else 'no'} |")
    rows.append(f"| Abandoned legs with handle time > 0 | 0.6% of abandons | {T['abandoned_with_handle_time']:,} | {dq['abandoned_handle_fixed']:,} fixed | "
                f"{'yes' if T['abandoned_with_handle_time'] == dq['abandoned_handle_fixed'] else 'no'} |")
    rows.append(f"| 'TS' alias rows for tech support | 15% of post-IVR tech legs | {T['tech_ts_code_rows']:,} | {dq['ts_rows']:,} mapped | "
                f"{'yes' if T['tech_ts_code_rows'] == dq['ts_rows'] else 'no'} |")
    rows.append(f"| Missing days | {', '.join(P['missing_days'])} | - | {c['dq_missing']} | "
                f"{'yes' if P['missing_days'] == dq['missing_dates'] else 'no'} |")
    c["validation_table"] = "\n".join(rows)
    return c


def main():
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    truth = json.loads((ROOT / "data" / "truth" / "planted_effects.json").read_text())
    ctx = build_context(res, truth)
    for tpl, out in [("README.md.tmpl", ROOT / "README.md"),
                     ("executive_summary.md.tmpl", ROOT / "docs" / "executive_summary.md")]:
        out.write_text((TPL / tpl).read_text().format_map(ctx))
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
