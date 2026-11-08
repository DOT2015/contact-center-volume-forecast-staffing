# Methodology

All data is synthetic (seed 42).

## Pipeline

`make all` runs `generate -> load -> clean -> analyze -> figures -> dashboard -> report -> powerbi`. The SQL runs in DuckDB in ANSI style (`AT TIME ZONE`, CTEs, window functions, `VALUES`, `DROP/CREATE TABLE AS`) and ports to PostgreSQL. Two DuckDB-specific pieces remain: `read_csv` (use `COPY` in PostgreSQL) and integer division, which is avoided by using `FLOOR(x / 2.0)`.

## Effect recovery

- **Day of week and trend:** a Poisson GLM of total daily contacts on weekday dummies (Thursday reference), months since start, open holidays, billing-cycle days, promotions, and outage load. Notice days are excluded. Standard errors are HC0. The weekday index is exp(coef).
- **Billing cycle:** the same model on the billing queue. `sql/03_analysis/02_*.sql` gives a weekday-matched SQL cross-check by year.
- **Intraday:** mean legs per half-hour on ordinary days (no holidays, promos, notice days, or missing days), pooled over queues and weekdays and divided by the mean of the 28 open intervals.
- **Outage elasticity:** the excess tech-support contacts in the 4 hours after an outage starts. The baseline is the same clock window on the same weekday in the 4 previous weeks. Slope fitted by least squares through the origin, with a t-interval.
- **Price notice:** per-queue Poisson GLMs fitted on 2025, excluding days -3..20 around the notice, give the counterfactual. The excess ratio for days 0..9 is fitted to `lift x 0.5^(k / half_life)` with `scipy.optimize.curve_fit`; CIs come from the covariance matrix. AHT lift = answered-leg AHT on days 0..13 vs. the 28 days before, with a delta-method CI.

## Forecasting

- **Target:** daily legs per queue (workload). Closed days are set to missing and forced to 0 in forecasts. The two missing ETL days are left missing.
- **Models:**
  1. Seasonal naive: repeat the last observed week.
  2. Holt-Winters ETS: damped additive trend and multiplicative weekly seasonality. Missing and closed days are imputed with the same weekday one week either side, for fitting only.
  3. Regression with AR(1) errors on log(legs) (statsmodels `SARIMAX`, which handles missing values in the state space). Regressors: month trend, weekday dummies, open holiday, billing-cycle day (billing), promo (moves), price-notice decay (billing, cancellations; half-life estimated from the event study), and outage load per 1,000 affected customers (tech). Point forecast = exp(mean + sigma^2 / 2). The 80% PI is exp(mean ± 1.2816 x SE).
- **No look-ahead:** future outage load is set to the training-period average. The price-notice regressor is known in advance (the event is on the business calendar), but its coefficient is dropped in folds whose training data does not yet include the 2025 notice.
- **Backtest:** 8 rolling origins, 28 days apart, each forecasting 91 days. The last fold ends on 2025-12-31. WAPE = sum |error| / sum actual. MASE = MAE / in-sample MAE of the lag-7 seasonal naive. Total-level MASE uses the summed series. Closed and missing days are not scored.
- **Total PI:** the queue PIs are combined assuming independent errors (variance from the PI width), which ignores cross-queue correlation.

## Staffing

1. Daily forecast by queue x the queue's share of the day per half-hour (same weekday, last 26 weeks of ordinary days, from `01_interval_volume_profile.sql`).
2. AHT per queue = Q4 2025 mean handle time of answered legs. The scenario adds the measured notice AHT lift to billing and cancellations for 14 days.
3. Erlang C (`src/erlang.py`): the smallest n with 1 - C(n, A) x exp(-(n - A) x 60 / AHT) >= 0.80, where A = calls x AHT / 1800 s.
4. Weekly FTE = sum of agents x 0.5 h / (1 - 0.32) / 40. This assumes perfect schedule fit.
5. Gap vs. a 48-FTE roster. Hires = ceiling of (peak full-week baseline requirement - roster). Hire-by = first gap week - 6 weeks; if that date has passed, hires become productive 6 weeks after 2026-01-01. Overtime hours = productive-hour shortfall per week after hires are ready, at $38 per hour.
6. Pooled alternative: all queues' calls per interval, AHT weighted by volume, one Erlang C team.

## Limitations

- Erlang C has no abandonment and assumes stationary Poisson arrivals within each interval. With 10% abandonment it overstates the agents needed, which makes this plan somewhat conservative.
- The intervals are applied to the mean forecast. The P90 view staffs every interval to the upper bound at the same time, which overstates the need. A better approach is simulation-based staffing to a service-level distribution.
- The price-notice estimate comes from one event. The 2026 scenario assumes the same response.
- Only two years of history, so no annual seasonality term.
- The 48-FTE roster is a simulated assumption. It was scaled down from the brief's 118 FTE so the volume fits the 500k-row fact-table standard.
