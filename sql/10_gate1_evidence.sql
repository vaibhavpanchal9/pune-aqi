-- Gate 1 (Sun 15 Nov 2026), condition 1: the cloud job has run unattended for 14+ days with no gap over
-- 12 hours. Only live runs count (backfill ran on the laptop, on purpose, on 27 Oct).

-- Q38. First unattended run, days running, number of runs, and the longest gap between successful runs.
WITH r AS (
    SELECT run_at, LAG(run_at) OVER (ORDER BY run_at) AS prev
    FROM ingestion_runs
    WHERE status IN ('ok', 'partial') AND mode = 'live' AND run_at >= '2026-10-26'
)
SELECT min(run_at)                                         AS first_run,
       round(EXTRACT(EPOCH FROM (now() - min(run_at))) / 86400, 1) AS days_running,
       count(*)                                            AS runs,
       max(run_at - prev)                                  AS longest_gap,
       round(avg(EXTRACT(EPOCH FROM (run_at - prev))) / 3600, 1) AS mean_gap_hours
FROM r;

-- Q39. The ten longest gaps, with when they ended — to see whether a gap was GitHub or something else.
WITH r AS (
    SELECT run_at, LAG(run_at) OVER (ORDER BY run_at) AS prev
    FROM ingestion_runs
    WHERE status IN ('ok', 'partial') AND mode = 'live' AND run_at >= '2026-10-26'
)
SELECT run_at AS resumed_at, run_at - prev AS gap
FROM r
WHERE prev IS NOT NULL
ORDER BY gap DESC
LIMIT 10;

-- Q40. Any failed runs at all since the clock started?
SELECT run_at, status, left(error_text, 80) AS error
FROM ingestion_runs
WHERE run_at >= '2026-10-26' AND status NOT IN ('ok', 'partial')
ORDER BY run_at;