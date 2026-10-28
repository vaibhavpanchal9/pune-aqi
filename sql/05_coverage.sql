-- 05 coverage: the hours that SHOULD exist vs the hours that DO.
-- generate_series makes one row per hour; LEFT JOIN marks which are present; count(column)
-- ignores NULLs, count(*) doesn't -- that difference is the whole trick.

-- Q18. Primary station: expected hours, present, missing, percent missing.
WITH hours AS (
    SELECT generate_series(
        (SELECT min(measured_at) FROM measurements WHERE sensor_id = 12238693),
        (SELECT max(measured_at) FROM measurements WHERE sensor_id = 12238693),
        interval '1 hour') AS ts
)
SELECT count(*)                 AS hours_expected,
       count(m.value)           AS hours_present,
       count(*) - count(m.value) AS hours_missing,
       round(100.0 * (count(*) - count(m.value)) / count(*), 1) AS pct_missing
FROM hours h
LEFT JOIN measurements m ON m.sensor_id = 12238693 AND m.measured_at = h.ts;

-- Q19. The same, month by month. Where are the primary station's holes?
WITH hours AS (
    SELECT generate_series(
        (SELECT min(measured_at) FROM measurements WHERE sensor_id = 12238693),
        (SELECT max(measured_at) FROM measurements WHERE sensor_id = 12238693),
        interval '1 hour') AS ts
)
SELECT to_char(date_trunc('month', h.ts), 'YYYY-MM') AS month,
       count(*) AS expected, count(m.value) AS present, count(*) - count(m.value) AS missing
FROM hours h
LEFT JOIN measurements m ON m.sensor_id = 12238693 AND m.measured_at = h.ts
GROUP BY 1
ORDER BY 1;

-- Q20. Every station over the same fixed window, so they are comparable. CROSS JOIN = every
--      sensor paired with every hour; then LEFT JOIN marks presence.
WITH hours AS (
    SELECT generate_series('2025-03-01 00:30+00'::timestamptz,
                           '2026-10-23 14:30+00'::timestamptz, interval '1 hour') AS ts
),
ids AS (SELECT DISTINCT sensor_id FROM measurements)
SELECT l.name AS station, i.sensor_id,
       count(*) AS expected, count(m.value) AS present,
       round(100.0 * (count(*) - count(m.value)) / count(*), 1) AS pct_missing
FROM ids i
CROSS JOIN hours h
LEFT JOIN measurements m ON m.sensor_id = i.sensor_id AND m.measured_at = h.ts
JOIN sensors   s ON s.sensor_id   = i.sensor_id
JOIN locations l ON l.location_id = s.location_id
GROUP BY l.name, i.sensor_id
ORDER BY pct_missing;