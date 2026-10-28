-- 01 basics: what is actually in the database?
-- Rule: before writing a query against a table, ask the database what columns it has.

-- Q1. What columns do the four tables have, and of what type?
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;

-- Q2. What does one row of measurements look like? (LIMIT: show me a few, not all 145k)
SELECT * FROM measurements LIMIT 5;

-- Q3. What does one row of sensors look like?
SELECT * FROM sensors WHERE is_active LIMIT 3;

-- Q4. How many rows, and how many per table?  (count(*) counts rows, nothing else)
SELECT 'measurements' AS tbl, count(*) FROM measurements
UNION ALL SELECT 'sensors', count(*) FROM sensors
UNION ALL SELECT 'locations', count(*) FROM locations
UNION ALL SELECT 'ingestion_runs', count(*) FROM ingestion_runs;

-- Q5. The five newest readings of the primary station. WHERE filters rows, ORDER BY sorts, LIMIT cuts.
SELECT * FROM measurements
WHERE sensor_id = 12238693
ORDER BY measured_at DESC
LIMIT 5;

-- Q6. The five OLDEST readings of the same station. One word changes.
SELECT * FROM measurements
WHERE sensor_id = 12238693
ORDER BY measured_at ASC
LIMIT 5;