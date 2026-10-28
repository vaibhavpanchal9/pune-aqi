-- 02 GROUP BY: one row per group, with a number computed over the group.

-- Q7. Per sensor: how many readings, and how polluted on average? (round(x::numeric, 1) = 1 decimal)
SELECT sensor_id, count(*) AS n, round(avg(value)::numeric, 1) AS avg_pm25,
       min(value) AS min_pm25, max(value) AS max_pm25
FROM measurements
GROUP BY sensor_id
ORDER BY avg_pm25 DESC;

-- Q8. Primary station, month by month. date_trunc collapses every timestamp in a month to the 1st.
SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month,
       count(*) AS n, round(avg(value)::numeric, 1) AS avg_pm25
FROM measurements
WHERE sensor_id = 12238693
GROUP BY 1
ORDER BY 1;

-- Q9. Average by hour of the day, in Pune time. AT TIME ZONE converts; EXTRACT pulls the hour out.
SELECT EXTRACT(HOUR FROM measured_at AT TIME ZONE 'Asia/Kolkata') AS hour_ist,
       round(avg(value)::numeric, 1) AS avg_pm25, count(*) AS n
FROM measurements
WHERE sensor_id = 12238693
GROUP BY 1
ORDER BY 1;

-- Q10. HAVING filters groups after they are formed (WHERE can't see count(*) yet).
--      Which months does the primary station have fewer than 600 readings in?
SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month, count(*) AS n
FROM measurements
WHERE sensor_id = 12238693
GROUP BY 1
HAVING count(*) < 600
ORDER BY 1;

-- Q11. The ten highest readings in the whole table. Are they real? (Step 5 decides.)
SELECT sensor_id, measured_at, value
FROM measurements
ORDER BY value DESC
LIMIT 10;