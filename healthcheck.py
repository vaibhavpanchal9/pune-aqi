"""Day 2, task 10. Is the pipeline alive?

    python healthcheck.py

Run this as the first task of every single day. It takes ten seconds and it
is the only thing standing between you and discovering in November that the
job silently died in September.

Exit code is 0 if healthy, 1 if not — so you can wire it into cron later
and have it shout at you.
"""

import sys
from db import get_conn

STALE_HOURS = 6          # how long without data before we call it broken


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

    healthy = hours_stale is not None and hours_stale < STALE_HOURS
    if healthy:
        print("  STATUS: OK\n")
        return 0

    print(f"  STATUS: STALE — no new data for over {STALE_HOURS} hours.")
    print("  Check: is the container up (docker ps)? Did cron fire")
    print("  (tail logs/ingest.log)? Is your API key still valid?\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
