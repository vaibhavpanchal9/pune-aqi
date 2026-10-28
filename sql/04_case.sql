-- 04 CASE: if/else inside a query. Also: CASE inside an aggregate = a conditional count.

-- Q15. CPCB categories for PM2.5 (ug/m3). How are the primary station's hours distributed?
SELECT CASE WHEN value <= 30  THEN '1 Good'
            WHEN value <= 60  THEN '2 Satisfactory'
            WHEN value <= 90  THEN '3 Moderate'
            WHEN value <= 120 THEN '4 Poor'
            WHEN value <= 250 THEN '5 Very poor'
            ELSE                   '6 Severe' END AS category,
       count(*) AS hours,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM measurements
WHERE sensor_id = 12238693
GROUP BY 1
ORDER BY 1;

-- Q16. Share of "Poor or worse" hours per month. avg() of 1s and 0s is a fraction.
SELECT to_char(date_trunc('month', measured_at), 'YYYY-MM') AS month,
       round(100 * avg(CASE WHEN value > 90 THEN 1 ELSE 0 END)::numeric, 1) AS pct_poor_or_worse,
       count(*) AS n
FROM measurements
WHERE sensor_id = 12238693
GROUP BY 1
ORDER BY 1;

-- Q17. Winter (Nov-Feb) vs the rest, per station. Month comes out of the IST timestamp.
SELECT l.name AS station,
       CASE WHEN EXTRACT(MONTH FROM m.measured_at AT TIME ZONE 'Asia/Kolkata') IN (11, 12, 1, 2)
            THEN 'winter' ELSE 'rest' END AS season,
       round(avg(m.value)::numeric, 1) AS avg_pm25, count(*) AS n
FROM measurements m
JOIN sensors   s ON s.sensor_id   = m.sensor_id
JOIN locations l ON l.location_id = s.location_id
GROUP BY 1, 2
ORDER BY 1, 2;