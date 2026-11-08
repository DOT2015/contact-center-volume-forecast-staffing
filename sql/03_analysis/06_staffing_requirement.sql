-- Q6. Staffing requirement: forecast legs x AHT -> Erlang C agents per interval (computed in
-- src/erlang.py and stored in fcst_interval_agents) -> weekly agent-hours -> FTE after 32% shrinkage,
-- compared with the 48-FTE roster. One row per week and scenario.

WITH params AS (SELECT 0.32 AS shrinkage, 40.0 AS hours_per_fte, 48.0 AS roster_fte),
wk AS (
    SELECT
        scenario,
        CAST(CAST(date AS DATE) - CAST(EXTRACT(isodow FROM date) - 1 AS INTEGER) AS DATE) AS week_start,
        SUM(agents_required) * 0.5      AS productive_agent_hours,
        SUM(agents_required_p90) * 0.5  AS productive_agent_hours_p90,
        SUM(forecast_legs)              AS forecast_legs
    FROM fcst_interval_agents
    GROUP BY scenario, 2
)
SELECT
    w.scenario, w.week_start, w.forecast_legs, w.productive_agent_hours,
    w.productive_agent_hours / (1 - p.shrinkage) / p.hours_per_fte          AS required_fte,
    w.productive_agent_hours_p90 / (1 - p.shrinkage) / p.hours_per_fte      AS required_fte_p90,
    p.roster_fte,
    w.productive_agent_hours / (1 - p.shrinkage) / p.hours_per_fte - p.roster_fte AS fte_gap
FROM wk w CROSS JOIN params p
ORDER BY w.scenario, w.week_start;
