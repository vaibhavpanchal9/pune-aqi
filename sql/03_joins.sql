-- 03 JOIN: combine tables through the ids they share.

-- Q12. Q7 again, but with station names. measurements -> sensors -> locations.
SELECT l.name AS station, m.sensor_id, count(*) AS n, round(avg(m.value)::numeric, 1) AS avg_pm25
FROM measurements m
JOIN sensors   s ON s.sensor_id   = m.sensor_id
JOIN locations l ON l.location_id = s.location_id
GROUP BY l.name, m.sensor_id
ORDER BY avg_pm25 DESC;

-- Q13. LEFT JOIN keeps rows with no match. Which registered PM2.5 sensors have ZERO measurements?
--      (Expect the dead ones and the retired twins -- the ones active_sensors() filters out.)
SELECT s.sensor_id, l.name AS station, s.is_active, s.datetime_last::date AS last_seen
FROM sensors s
JOIN locations l ON l.location_id = s.location_id
LEFT JOIN measurements m ON m.sensor_id = s.sensor_id
WHERE s.parameter = 'pm25'
GROUP BY s.sensor_id, l.name, s.is_active, s.datetime_last
HAVING count(m.sensor_id) = 0
ORDER BY s.is_active DESC, last_seen DESC;

-- Q14a. Which station was silent June-November 2025? With an inner JOIN the silent one simply
--       disappears from the list -- you have to notice what's missing.
SELECT l.name AS station, count(*) AS n
FROM measurements m
JOIN sensors   s ON s.sensor_id   = m.sensor_id
JOIN locations l ON l.location_id = s.location_id
WHERE m.measured_at >= '2025-06-01' AND m.measured_at < '2025-12-01'
GROUP BY l.name
ORDER BY n;

-- Q14b. Same question with a LEFT JOIN and the date filter in the ON clause (not WHERE):
--       the silent station now shows up with 0. Compare the two outputs.
SELECT l.name AS station, count(m.sensor_id) AS n
FROM sensors s
JOIN locations l ON l.location_id = s.location_id
LEFT JOIN measurements m
       ON m.sensor_id = s.sensor_id
      AND m.measured_at >= '2025-06-01' AND m.measured_at < '2025-12-01'
WHERE s.sensor_id IN (SELECT DISTINCT sensor_id FROM measurements)
GROUP BY l.name
ORDER BY n;