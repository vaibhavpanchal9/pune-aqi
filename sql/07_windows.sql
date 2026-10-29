-- 07 window functions: a value computed from a row's neighbours, one result per row.

-- Q21. LAG = the previous row's value. Hour-to-hour change at Pashan, last 24 rows.
SELECT measured_at, value,
       LAG(value) OVER (ORDER BY measured_at)         AS prev_value,
       value - LAG(value) OVER (ORDER BY measured_at) AS change
FROM measurements
WHERE sensor_id = 12238693
ORDER BY measured_at DESC
LIMIT 24;

-- Q22. LAG on the timestamp itself = the gap since the previous row. The ten longest gaps at Pashan.
--      This finds outages directly: a gap of 1 hour is normal, anything bigger is a hole.
SELECT measured_at                                              AS resumed_at,
       LAG(measured_at) OVER (ORDER BY measured_at)             AS last_before_gap,
       measured_at - LAG(measured_at) OVER (ORDER BY measured_at) AS gap
FROM measurements
WHERE sensor_id = 12238693
ORDER BY gap DESC NULLS LAST
LIMIT 10;

-- Q23. ROWS vs TIME. "Average of the previous 24 rows" and "average of the previous 24 hours" are
--      different things when hours are missing. Both computed; compare them on rows right after a gap.
SELECT measured_at, value,
       round(avg(value) OVER (ORDER BY measured_at
                              ROWS  BETWEEN 23 PRECEDING AND CURRENT ROW)::numeric, 1) AS avg_24_rows,
       round(avg(value) OVER (ORDER BY measured_at
                              RANGE BETWEEN interval '23 hours' PRECEDING AND CURRENT ROW)::numeric, 1) AS avg_24_hours,
       count(*) OVER (ORDER BY measured_at
                      RANGE BETWEEN interval '23 hours' PRECEDING AND CURRENT ROW) AS hours_actually_present
FROM measurements
WHERE sensor_id = 12238693
  AND measured_at BETWEEN '2026-01-20' AND '2026-02-05'
ORDER BY measured_at;

-- Q24. PARTITION BY = restart the window for each group. The worst hour of each day, January 2026.
SELECT *
FROM (
    SELECT (measured_at AT TIME ZONE 'Asia/Kolkata')::date AS day_ist,
           measured_at, value,
           RANK() OVER (PARTITION BY (measured_at AT TIME ZONE 'Asia/Kolkata')::date
                        ORDER BY value DESC) AS rank_in_day
    FROM measurements
    WHERE sensor_id = 12238693
      AND measured_at >= '2025-12-31 18:30+00' AND measured_at < '2026-01-31 18:30+00'
) t
WHERE rank_in_day = 1
ORDER BY day_ist;

-- Q25. LAG over groups: month-over-month change of the monthly average (builds on Q8).
WITH monthly AS (
    SELECT date_trunc('month', measured_at) AS month, round(avg(value)::numeric, 1) AS avg_pm25
    FROM measurements
    WHERE sensor_id = 12238693
    GROUP BY 1
)
SELECT to_char(month, 'YYYY-MM') AS month, avg_pm25,
       avg_pm25 - LAG(avg_pm25) OVER (ORDER BY month) AS change_vs_prev_month
FROM monthly
ORDER BY month;