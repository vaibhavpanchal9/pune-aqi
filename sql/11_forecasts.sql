-- Step 10: the forecasts table as evidence. Run after forecast.py has written at least once:
--     python runsql.py sql/11_forecasts.sql
-- Q43 and Q44 start empty/small and fill up as target hours arrive; rerun them daily.

-- Q41: the forecasts currently on file for hours still ahead (what the API will serve)
SELECT to_char(target_time AT TIME ZONE 'Asia/Kolkata', 'Dy DD Mon HH24:MI') AS target_ist,
       round(point::numeric, 1) AS point,
       round(lower::numeric, 1) AS lower,
       round(upper::numeric, 1) AS upper,
       round((EXTRACT(EPOCH FROM (target_time - now())) / 3600)::numeric, 1) AS hours_ahead,
       to_char(issued_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS issued_ist,
       model_version
FROM forecasts
WHERE sensor_id = 12238693 AND target_time > now()
ORDER BY target_time;

-- Q42: lead time. issued - origin = how late the data was + the hourly cadence; target - issued = real lead
SELECT count(*) AS forecasts,
       round(avg(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600)::numeric, 1) AS mean_issue_delay_h,
       round(max(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600)::numeric, 1) AS max_issue_delay_h,
       round(avg(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)::numeric, 1) AS mean_lead_h,
       round(min(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)::numeric, 1) AS min_lead_h
FROM forecasts
WHERE sensor_id = 12238693 AND model_version = 'v1';

-- Q43: live accuracy. Forecasts whose target hour has a reading, scored against it (the /stats number).
--      The actual is kept only if the value policy would keep it (positive, below 985).
--      persistence_mae = the same hours forecast by "same as the origin hour", for comparison.
SELECT count(*) AS scored,
       round(avg(abs(f.point - m.value))::numeric, 2) AS mae,
       round(avg(f.point - m.value)::numeric, 2) AS bias,
       round(avg((m.value BETWEEN f.lower AND f.upper)::int)::numeric, 3) AS coverage_80,
       round(avg(f.upper - f.lower)::numeric, 1) AS mean_width,
       round(avg(abs(o.value - m.value))::numeric, 2) AS persistence_mae,
       min(f.target_time) AS first_scored,
       max(f.target_time) AS last_scored
FROM forecasts f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
LEFT JOIN measurements o
  ON o.sensor_id = f.sensor_id AND o.measured_at = f.origin_time AND o.source = 'openaq'
WHERE f.sensor_id = 12238693 AND f.model_version = 'v1'
  AND m.value > 0 AND m.value < 985;

-- Q44: availability. Of the last 7 days' hours that have passed, how many had a forecast on file?
--      (none when a feature was missing at issue time: a gap longer than 3 h removes rows at every lag offset)
SELECT count(*) AS hours_with_forecast,
       168 AS hours_in_week,
       round(count(*)::numeric / 168, 3) AS availability
FROM forecasts
WHERE sensor_id = 12238693 AND model_version = 'v1'
  AND target_time > now() - interval '7 days' AND target_time <= now();
