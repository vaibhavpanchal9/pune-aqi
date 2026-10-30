"""Step 5. Data-quality audit. Prints the tables docs/data_quality.md is written from.

    python quality_report.py                      # per-station tables + detail for the primary station
    python quality_report.py --sensor 12236449    # detail for another station

Every rule in docs/decisions.md ("gap policy", "value policy") must point at a number printed here.
"""

import argparse

from db import get_conn
from runsql import print_rows

PRIMARY = 12238693

SECTIONS = [
("A. Gap lengths at the chosen station — how long are the holes, and how many hours do they cost?", """
WITH g AS (
    SELECT measured_at - LAG(measured_at) OVER (ORDER BY measured_at) AS gap
    FROM measurements
    WHERE sensor_id = %(sid)s
)
SELECT CASE WHEN gap <= interval '1 hour'   THEN '1  no gap'
            WHEN gap <= interval '3 hours'  THEN '2  1-2 h missing'
            WHEN gap <= interval '6 hours'  THEN '3  3-5 h missing'
            WHEN gap <= interval '24 hours' THEN '4  6-23 h missing'
            ELSE                                 '5  a day or more' END AS bucket,
       count(*)                                          AS n_gaps,
       sum(EXTRACT(EPOCH FROM gap) / 3600 - 1)::int      AS hours_missing
FROM g
WHERE gap IS NOT NULL
GROUP BY 1
ORDER BY 1;
"""),

("B. Missing hours per month at the chosen station (from the grid)", """
SELECT to_char(date_trunc('month', ts), 'YYYY-MM') AS month,
       count(*) AS grid_hours, count(value) AS present, count(*) - count(value) AS missing,
       round(100.0 * (count(*) - count(value)) / count(*), 1) AS pct_missing
FROM v_features
WHERE sensor_id = %(sid)s
GROUP BY 1
ORDER BY 1;
"""),

("C. Impossible and suspicious values, per station. spike/dropout = more than 4x above/below BOTH neighbours.", """
WITH x AS (
    SELECT m.sensor_id, l.name, m.value,
           LAG(m.value)  OVER (PARTITION BY m.sensor_id ORDER BY m.measured_at) AS prev,
           LEAD(m.value) OVER (PARTITION BY m.sensor_id ORDER BY m.measured_at) AS nxt
    FROM measurements m
    JOIN sensors   s ON s.sensor_id   = m.sensor_id
    JOIN locations l ON l.location_id = s.location_id
)
SELECT name AS station, sensor_id, count(*) AS n,
       count(*) FILTER (WHERE value < 0)      AS negative,
       count(*) FILTER (WHERE value = 0)      AS zero,
       count(*) FILTER (WHERE value >= 985)   AS ceiling_985plus,
       count(*) FILTER (WHERE prev > 0 AND nxt > 0 AND value > 4 * prev AND value > 4 * nxt) AS spike_4x,
       count(*) FILTER (WHERE prev > 0 AND nxt > 0 AND value > 0
                          AND value < prev / 4 AND value < nxt / 4)                       AS dropout_4x
FROM x
GROUP BY 1, 2
ORDER BY 1;
"""),

("D. Stuck sensors: runs of 6+ consecutive identical values (gaps-and-islands with window functions)", """
WITH r AS (
    SELECT sensor_id, measured_at, value,
           CASE WHEN value = LAG(value) OVER (PARTITION BY sensor_id ORDER BY measured_at)
                THEN 0 ELSE 1 END AS starts_new_run
    FROM measurements
),
runs AS (
    SELECT sensor_id, value,
           sum(starts_new_run) OVER (PARTITION BY sensor_id ORDER BY measured_at) AS run_id
    FROM r
),
lens AS (
    SELECT sensor_id, run_id, value, count(*) AS len
    FROM runs
    GROUP BY 1, 2, 3
)
SELECT l.name AS station, lens.sensor_id,
       count(*) AS flat_runs_6plus, max(len) AS longest_run, sum(len) AS hours_in_flat_runs,
       round(avg(value)::numeric, 1) AS avg_stuck_value
FROM lens
JOIN sensors   s ON s.sensor_id   = lens.sensor_id
JOIN locations l ON l.location_id = s.location_id
WHERE len >= 6
GROUP BY 1, 2
ORDER BY hours_in_flat_runs DESC;
"""),

("E. Timestamp alignment: every reading should sit on :30 UTC (an IST hour). Anything else is off-grid.", """
SELECT EXTRACT(MINUTE FROM measured_at)::int AS minute, count(*) AS n
FROM measurements
GROUP BY 1
ORDER BY 1;
"""),

("F. Network-wide outage days: fewer than half of the possible 13 x 24 readings across all stations", """
WITH days AS (
    SELECT generate_series(date '2025-03-01', current_date, interval '1 day')::date AS day
),
daily AS (
    SELECT measured_at::date AS day, count(*) AS readings, count(DISTINCT sensor_id) AS stations
    FROM measurements
    GROUP BY 1
)
SELECT d.day, coalesce(x.readings, 0) AS readings, coalesce(x.stations, 0) AS stations
FROM days d
LEFT JOIN daily x ON x.day = d.day
WHERE coalesce(x.readings, 0) < 0.5 * 13 * 24
ORDER BY d.day;
"""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY, help="station for sections A and B")
    args = ap.parse_args()

    with get_conn() as conn, conn.cursor() as cur:
        for title, sql in SECTIONS:
            print("=" * 100)
            print(title)
            print("=" * 100)
            cur.execute(sql, {"sid": args.sensor})
            print_rows(cur)


if __name__ == "__main__":
    main()