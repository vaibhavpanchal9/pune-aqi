-- -- Q9. Average by hour of the day, in Pune time. AT TIME ZONE converts; EXTRACT pulls the hour out.
-- SELECT EXTRACT(HOUR FROM measured_at AT TIME ZONE 'Asia/Kolkata') AS hour_ist,
--        round(avg(value)::numeric, 1) AS avg_pm25, count(*) AS n
-- FROM measurements
-- WHERE sensor_id = 12238693
-- GROUP BY 1
-- ORDER BY 1;


-- -- E1. Hadapsar's daily shape
-- SELECT EXTRACT(HOUR FROM measured_at AT TIME ZONE 'Asia/Kolkata') AS hour_ist,
--        round(avg(value)::numeric, 1) AS avg_pm25, count(*) AS n
-- FROM measurements
-- WHERE sensor_id = 12236449
-- GROUP BY 1
-- ORDER BY 1;


-- -- Q16. Share of "Poor or worse" hours per month. avg() of 1s and 0s is a fraction.
-- SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month,
--        round(100 * avg(CASE WHEN value > 90 THEN 1 ELSE 0 END)::numeric, 1) AS pct_poor_or_worse,
--        count(*) AS n
-- FROM measurements
-- WHERE sensor_id = 12238693
-- GROUP BY 1
-- ORDER BY 1;

-- -- E2. Satisfactory or worse (>30), share per month
-- SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month,
--        round(100 * avg(CASE WHEN value > 30 THEN 1 ELSE 0 END)::numeric, 1) AS pct_satisfactory_or_worse,
--        count(*) AS n
-- FROM measurements
-- WHERE sensor_id = 12238693
-- GROUP BY 1
-- ORDER BY 1;

-- E3. Station-months missing more than 100 hours
WITH hours AS (
    SELECT generate_series('2025-03-01 00:30+00'::timestamptz,
                           '2026-10-23 14:30+00'::timestamptz, interval '1 hour') AS ts
),
ids AS (SELECT DISTINCT sensor_id FROM measurements)
SELECT to_char(date_trunc('month', h.ts), 'YYYY-MM') AS month,      -- NEW: the month of each hour
       l.name AS station, i.sensor_id,
       count(*) AS expected, count(m.value) AS present,
       count(*) - count(m.value) AS missing                          -- CHANGED: a count, not a percent
FROM ids i
CROSS JOIN hours h
LEFT JOIN measurements m ON m.sensor_id = i.sensor_id AND m.measured_at = h.ts
JOIN sensors   s ON s.sensor_id   = i.sensor_id
JOIN locations l ON l.location_id = s.location_id
GROUP BY month, l.name, i.sensor_id                                 -- CHANGED: one group per station AND month
HAVING count(*) - count(m.value) > 100                              -- NEW: keep only the bad ones
ORDER BY month, missing DESC;                                       -- CHANGED