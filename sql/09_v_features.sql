-- 09 v_features: the training table. Rows are grid hours; a missing hour is a NULL row.

-- Q33. Done-when for today: rows that have a full week of history behind them, all stations.
SELECT count(*) AS rows_with_week_history
FROM v_features
WHERE lag_168 IS NOT NULL;

-- Q34. Primary station: grid hours, hours with a reading, and rows usable for training
--      (reading present, the lags present, and the 24 h-ahead target present).
SELECT count(*)      AS grid_hours,
       count(value)  AS hours_with_reading,
       count(*) FILTER (WHERE value IS NOT NULL AND lag_24 IS NOT NULL
                          AND lag_168 IS NOT NULL AND y_24h_ahead IS NOT NULL) AS usable_training_rows,
       min(ts) AS first_ts, max(ts) AS last_ts
FROM v_features
WHERE sensor_id = 12238693;

-- Q35. The 4 February gap, seen from the grid: NULL rows for the missing hours, and roll_24
--      honestly built from n_24 hours instead of reaching back two days.
SELECT ts, value, lag_1, lag_24, n_24, round(roll_24::numeric, 1) AS roll_24, y_24h_ahead
FROM v_features
WHERE sensor_id = 12238693
  AND ts BETWEEN '2026-02-03 06:30+00' AND '2026-02-04 12:30+00'
ORDER BY ts;

-- Q36. A correctness test, in SQL: lag_24 must equal the reading exactly 24 hours earlier.
--      If any row says false, the view is wrong and nothing built on it can be trusted.
SELECT count(*) AS rows_checked,
       count(*) FILTER (WHERE f.lag_24 = m.value)  AS rows_correct,
       count(*) FILTER (WHERE f.lag_24 <> m.value) AS rows_wrong
FROM v_features f
JOIN measurements m
  ON m.sensor_id = f.sensor_id AND m.measured_at = f.ts - interval '24 hours'
WHERE f.sensor_id = 12238693;

-- Q37. What does the view cost? Step 6 will read it; know the price before building on it.
EXPLAIN (ANALYZE)
SELECT count(*) FROM v_features WHERE sensor_id = 12238693;
