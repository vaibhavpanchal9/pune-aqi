-- Step 10: the forecasts table as evidence. Run after forecast.py has written at least once:
--     python runsql.py sql/11_forecasts.sql
-- The scores fill up as target hours arrive; rerun daily.

-- Q41: the forecasts on file for hours still ahead, newest model version (what the API serves)
SELECT to_char(target_time AT TIME ZONE 'Asia/Kolkata', 'Dy DD Mon HH24:MI') AS target_ist,
       round(point::numeric, 1) AS point,
       round(lower::numeric, 1) AS lower,
       round(upper::numeric, 1) AS upper,
       round((EXTRACT(EPOCH FROM (target_time - now())) / 3600)::numeric, 1) AS hours_ahead,
       tier,
       to_char(issued_at AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS issued_ist,
       model_version
FROM forecasts
WHERE sensor_id = 12238693 AND target_time > now()
  AND model_version = (SELECT max(model_version) FROM forecasts WHERE sensor_id = 12238693)
ORDER BY target_time;

-- Q42: lead time per model version. issued - origin = how late the data was; target - issued = real lead
SELECT model_version,
       count(*) AS forecasts,
       round(avg(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600)::numeric, 1) AS mean_issue_delay_h,
       round(max(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600)::numeric, 1) AS max_issue_delay_h,
       round(avg(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)::numeric, 1) AS mean_lead_h,
       round(min(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)::numeric, 1) AS min_lead_h
FROM forecasts
WHERE sensor_id = 12238693
GROUP BY model_version
ORDER BY model_version;

-- Q43: live accuracy per model version and tier. Forecasts whose target hour has a reading, scored as issued.
--      The actual is kept only if the value policy would keep it (positive, below 985).
--      persistence_mae = the same hours forecast by "same as the origin hour", for comparison.
SELECT f.model_version, f.tier,
       count(*) AS scored,
       round(avg(abs(f.point - m.value))::numeric, 2) AS mae,
       round(avg(f.point - m.value)::numeric, 2) AS bias,
       round(avg((m.value BETWEEN f.lower AND f.upper)::int)::numeric, 3) AS coverage_80,
       round(avg(f.upper - f.lower)::numeric, 1) AS mean_width,
       round(avg(abs(o.value - m.value))::numeric, 2) AS persistence_mae,
       to_char(min(f.target_time) AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS first_ist,
       to_char(max(f.target_time) AT TIME ZONE 'Asia/Kolkata', 'DD Mon HH24:MI') AS last_ist
FROM forecasts f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
LEFT JOIN measurements o
  ON o.sensor_id = f.sensor_id AND o.measured_at = f.origin_time AND o.source = 'openaq'
WHERE f.sensor_id = 12238693
  AND m.value > 0 AND m.value < 985
GROUP BY f.model_version, f.tier
ORDER BY f.model_version, f.tier;

-- Q44: availability. Of the last 7 days' hours that have passed, how many had a forecast on file (any version)?
SELECT count(DISTINCT target_time) AS hours_with_forecast,
       168 AS hours_in_week,
       round(count(DISTINCT target_time)::numeric / 168, 3) AS availability
FROM forecasts
WHERE sensor_id = 12238693
  AND target_time > now() - interval '7 days' AND target_time <= now();

-- Q45: availability day by day (IST): hours with a forecast, and which tier made them
SELECT to_char((target_time AT TIME ZONE 'Asia/Kolkata')::date, 'Dy DD Mon') AS day_ist,
       count(DISTINCT target_time) AS hours_with_forecast,
       count(*) FILTER (WHERE tier = 'full')  AS full_tier,
       count(*) FILTER (WHERE tier = 'day')   AS day_tier,
       count(*) FILTER (WHERE tier = 'short') AS short_tier
FROM forecasts
WHERE sensor_id = 12238693 AND target_time <= now()
GROUP BY (target_time AT TIME ZONE 'Asia/Kolkata')::date
ORDER BY (target_time AT TIME ZONE 'Asia/Kolkata')::date;
