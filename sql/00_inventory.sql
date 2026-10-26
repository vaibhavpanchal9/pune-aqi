-- Step 3 inventory. Every number in docs/data_inventory.md comes from here.

-- 1. Totals
SELECT count(*) AS rows_total, count(DISTINCT sensor_id) AS sensors,
       min(measured_at) AS first_reading, max(measured_at) AS last_reading
FROM measurements;

-- 2. One line per station: how much of its own span is actually present
SELECT l.name AS station, m.sensor_id,
       min(m.measured_at)::date AS first_day, max(m.measured_at)::date AS last_day,
       count(*) AS rows_held,
       round(100.0 * count(*)
             / (EXTRACT(EPOCH FROM (max(m.measured_at) - min(m.measured_at))) / 3600 + 1), 1)
         AS pct_hours_present
FROM measurements m
JOIN sensors s   ON s.sensor_id = m.sensor_id
JOIN locations l ON l.location_id = s.location_id
GROUP BY l.name, m.sensor_id
ORDER BY pct_hours_present DESC;

-- 3. Rows per month: where are the holes?
SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month,
       count(*) AS rows_held, count(DISTINCT sensor_id) AS sensors_reporting
FROM measurements
GROUP BY 1 ORDER BY 1;