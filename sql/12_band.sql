-- Step 15: where the live band misses. Run:
--     python runsql.py sql/12_band.sql
-- "Scored" = the target hour has a reading that the value policy keeps (positive, below 985).

-- Q46: live band per version and tier: actuals below it, inside it, above it
SELECT f.model_version, f.tier,
       count(*) AS scored,
       count(*) FILTER (WHERE m.value < f.lower) AS below,
       count(*) FILTER (WHERE m.value BETWEEN f.lower AND f.upper) AS inside,
       count(*) FILTER (WHERE m.value > f.upper) AS above,
       round(avg((m.value < f.lower)::int)::numeric, 3) AS share_below,
       round(avg((m.value BETWEEN f.lower AND f.upper)::int)::numeric, 3) AS coverage_80,
       round(avg((m.value > f.upper)::int)::numeric, 3) AS share_above
FROM forecasts f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
WHERE f.sensor_id = 12238693
  AND m.value > 0 AND m.value < 985
GROUP BY f.model_version, f.tier
ORDER BY f.model_version, f.tier;

-- Q47: live relative error, (actual - point) / max(point, 1), next to the band's own edges
SELECT f.model_version, f.tier,
       count(*) AS scored,
       round(percentile_cont(0.10) WITHIN GROUP (ORDER BY (m.value - f.point) / greatest(f.point, 1))::numeric, 3) AS live_p10,
       round(avg((f.lower - f.point) / greatest(f.point, 1))::numeric, 3) AS band_lower,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY (m.value - f.point) / greatest(f.point, 1))::numeric, 3) AS live_p50,
       round(percentile_cont(0.90) WITHIN GROUP (ORDER BY (m.value - f.point) / greatest(f.point, 1))::numeric, 3) AS live_p90,
       round(avg((f.upper - f.point) / greatest(f.point, 1))::numeric, 3) AS band_upper
FROM forecasts f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
WHERE f.sensor_id = 12238693
  AND m.value > 0 AND m.value < 985
GROUP BY f.model_version, f.tier
ORDER BY f.model_version, f.tier;

-- Q48: newest version, day by day (IST): actual vs forecast, misses below and above
SELECT to_char((f.target_time AT TIME ZONE 'Asia/Kolkata')::date, 'Dy DD Mon') AS day_ist,
       count(*) AS scored,
       round(avg(m.value)::numeric, 1) AS mean_actual,
       round(avg(f.point)::numeric, 1) AS mean_forecast,
       round(avg(f.point - m.value)::numeric, 1) AS bias,
       round(avg(abs(f.point - m.value))::numeric, 1) AS mae,
       round(avg(abs(o.value - m.value))::numeric, 1) AS persistence_mae,
       count(*) FILTER (WHERE m.value < f.lower) AS below,
       count(*) FILTER (WHERE m.value > f.upper) AS above,
       round(avg((m.value BETWEEN f.lower AND f.upper)::int)::numeric, 2) AS coverage_80
FROM forecasts f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
LEFT JOIN measurements o
  ON o.sensor_id = f.sensor_id AND o.measured_at = f.origin_time AND o.source = 'openaq'
WHERE f.sensor_id = 12238693
  AND m.value > 0 AND m.value < 985
  AND f.model_version = (SELECT max(model_version) FROM forecasts WHERE sensor_id = 12238693)
GROUP BY (f.target_time AT TIME ZONE 'Asia/Kolkata')::date
ORDER BY (f.target_time AT TIME ZONE 'Asia/Kolkata')::date;
