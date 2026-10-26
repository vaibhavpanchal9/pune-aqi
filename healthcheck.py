"""Is the pipeline alive?

    python healthcheck.py

Run it first thing every day (ten seconds). It also runs as the last step of
the GitHub Actions job. It answers two different questions separately:

  * Did OUR job run successfully recently?        -> if not, exit 1 (job turns red)
  * Is THEIR data (CPCB via OpenAQ) fresh?         -> if not, warn but exit 0;
                                                      nothing on our side can fix it

Mixing the two means the alarm blames you for their outage. On 26 Oct 2026 the
whole Pune feed stopped for three days while this job ran fine every two hours.
"""

import os                # NEW
import sys

from db import get_conn

STALE_HOURS = 6          # no successful run for this long = OUR pipeline is broken
UPSTREAM_HOURS = 6       # NEW: newest reading older than this = THEIR feed is lagging


def main():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM measurements")
        total_rows = cur.fetchone()[0]

        cur.execute("""
            SELECT max(measured_at),
                   EXTRACT(EPOCH FROM (now() - max(measured_at))) / 3600
            FROM measurements
        """)
        latest, hours_stale = cur.fetchone()

        cur.execute("""
            SELECT min(measured_at), max(measured_at),
                   count(DISTINCT sensor_id)
            FROM measurements
        """)
        first_reading, last_reading, n_sensors = cur.fetchone()

        cur.execute("""
            SELECT status, count(*)
            FROM ingestion_runs
            WHERE run_at > now() - interval '24 hours'
            GROUP BY status ORDER BY status
        """)
        recent_runs = cur.fetchall()

        cur.execute("""
            SELECT run_at, status, rows_inserted, error_text
            FROM ingestion_runs ORDER BY run_at DESC LIMIT 1
        """)
        last_run = cur.fetchone()

        # The number that eventually goes on your resume.
        cur.execute("""
            SELECT EXTRACT(DAY FROM (now() - min(run_at)))
            FROM ingestion_runs WHERE status IN ('ok', 'partial')
        """)
        days_running = cur.fetchone()[0]

        # NEW: age of OUR last successful run — this decides red or green.
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (now() - max(run_at))) / 3600
            FROM ingestion_runs WHERE status IN ('ok', 'partial')
        """)
        hours_since_ok_run = cur.fetchone()[0]

    print("=" * 58)
    print("  PUNE AQI PIPELINE HEALTH")
    print("=" * 58)
    print(f"  total rows          : {total_rows:,}")
    print(f"  distinct sensors    : {n_sensors}")
    print(f"  data range          : {first_reading}  ->  {last_reading}")
    print(f"  hours since newest  : {hours_stale:.1f}" if hours_stale is not None
          else "  hours since newest  : no data yet")
    print(f"  days collecting     : {int(days_running) if days_running else 0}")
    print("-" * 58)
    print("  runs in last 24h    :", ", ".join(f"{s}={c}" for s, c in recent_runs) or "none")
    if last_run:
        run_at, status, inserted, err = last_run
        print(f"  last run            : {run_at:%Y-%m-%d %H:%M}  {status}  (+{inserted} rows)")
        if err:
            print(f"  last error          : {err[:120]}")
    print("=" * 58)

    # NEW from here down: two verdicts instead of one.
    pipeline_ok = hours_since_ok_run is not None and hours_since_ok_run < STALE_HOURS
    upstream_ok = hours_stale is not None and hours_stale < UPSTREAM_HOURS

    if not pipeline_ok:
        age = f"{hours_since_ok_run:.1f} h ago" if hours_since_ok_run is not None else "never"
        print(f"  STATUS: BROKEN — last successful run: {age} (limit {STALE_HOURS} h).")
        print("  Check the Actions tab: did the schedule fire? Are the two secrets")
        print("  still valid? Read 'last error' above.\n")
        return 1

    if not upstream_ok:
        age = f"{hours_stale:.1f} h old" if hours_stale is not None else "absent"
        print(f"  STATUS: OK (our job runs) — UPSTREAM LAG: newest reading is {age}.")
        print("  Nothing to fix here. If it lasts more than a day, note the dates")
        print("  in docs/data_quality.md.\n")
        if os.getenv("GITHUB_ACTIONS"):
            # GitHub turns this line into a yellow annotation on the run page.
            print(f"::warning::upstream lag: newest reading is {age}; our job is fine")
        return 0

    print("  STATUS: OK\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())