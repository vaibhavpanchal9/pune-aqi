-- 08 EXPLAIN: how Postgres runs a query, and how long it really takes.
-- Read each plan bottom-up. "Seq Scan" = read the whole table. "Index Scan" = jump straight to the rows.
-- "actual time=a..b" on the top line is the real duration in ms; "Buffers: shared hit" = pages from cache.

-- Q26. One sensor + a time range. The primary key starts with sensor_id, so expect an Index Scan.
EXPLAIN (ANALYZE, BUFFERS)
SELECT measured_at, value
FROM measurements
WHERE sensor_id = 12238693 AND measured_at >= now() - interval '7 days'
ORDER BY measured_at;

-- Q27. A time range across ALL sensors. The PK can't help: its first column is sensor_id, and we
--      aren't filtering on it. Expect a Seq Scan over the whole table.
EXPLAIN (ANALYZE, BUFFERS)
SELECT sensor_id, round(avg(value)::numeric, 1) AS avg_pm25
FROM measurements
WHERE measured_at >= '2026-10-01'
GROUP BY sensor_id;

-- Q28. The healthcheck's own question, asked every two hours by the cloud job. How is it answered?
EXPLAIN (ANALYZE, BUFFERS)
SELECT max(measured_at) FROM measurements;

-- Q29. Add an index on measured_at alone. IF NOT EXISTS makes this safe to run twice.
CREATE INDEX IF NOT EXISTS measurements_measured_at_idx ON measurements (measured_at);

-- Q27 again, after the index.
EXPLAIN (ANALYZE, BUFFERS)
SELECT sensor_id, round(avg(value)::numeric, 1) AS avg_pm25
FROM measurements
WHERE measured_at >= '2026-10-01'
GROUP BY sensor_id;

-- Q28 again, after the index.
EXPLAIN (ANALYZE, BUFFERS)
SELECT max(measured_at) FROM measurements;

-- Q30. The index was already there (idx_measurements_time, August). To see what it saves, forbid
--      index scans for this session and run Q27 again. SET lasts until RESET or disconnect.
SET enable_indexscan = off;
SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sensor_id, round(avg(value)::numeric, 1) AS avg_pm25
FROM measurements
WHERE measured_at >= '2026-10-01'
GROUP BY sensor_id;
RESET enable_indexscan;
RESET enable_bitmapscan;

-- Q31. Look before you add: every index on measurements, with its definition.
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'measurements';

-- Q32. Remove the duplicate from Q29. The August index does the same job.
DROP INDEX IF EXISTS measurements_measured_at_idx;