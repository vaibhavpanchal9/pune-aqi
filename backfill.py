"""Step 3. Backfill every hour since the sensors restarted (Feb 2025), one month at a time.

    python backfill.py                       # 2025-02-18 -> today
    python backfill.py --start 2026-06-01    # a later start, if you ever need one

Why month by month and not one 20-month window: progress you can watch, one
ingestion_runs row per month, a commit per month, and if it dies halfway you
just run it again -- months that are already full are skipped.

The skip rule looks at the WORST sensor in the month, not the total. If a run
died after 8 of 13 sensors, the other 5 have zero rows for that month and the
month is fetched again. A month where every sensor already has at least half
of its possible hours was certainly fetched before, so it is skipped.
"""

import argparse
from datetime import date, timedelta

from db import get_conn
from ingest import run_ingest, active_sensors, log

FIRST_DAY = date(2025, 2, 18)   # every live Pune sensor restarts on this date (audit_sensors.py)
FULL_ENOUGH = 0.5               # worst sensor has >= 50% of the month's hours -> skip the month


def month_windows(start, end):
    """Yield (from, to) date pairs: start -> 1st of next month -> ... -> end. `to` is exclusive."""
    cur = start
    while cur < end:
        first_of_next = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(first_of_next, end)
        cur = first_of_next


def sensor_rows(conn, sensor_id, d_from, d_to):
    """How many hourly rows this sensor already has inside the window."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM measurements "
            "WHERE sensor_id = %s AND measured_at >= %s AND measured_at < %s",
            (sensor_id, d_from, d_to),
        )
        return cur.fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=FIRST_DAY.isoformat(), help="YYYY-MM-DD, inclusive")
    ap.add_argument("--end", default=date.today().isoformat(), help="YYYY-MM-DD, exclusive")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    with get_conn() as conn:
        sensors = active_sensors(conn)
        log.info("backfill %s -> %s for %d sensors", start, end, len(sensors))

        for d_from, d_to in month_windows(start, end):
            possible = (d_to - d_from).days * 24
            worst = min(sensor_rows(conn, sid, d_from, d_to) for sid, _ in sensors)
            if worst >= FULL_ENOUGH * possible:
                log.info("%s -> %s: worst sensor has %d of %d hours, skipping", d_from, d_to, worst, possible)
                continue
            log.info("%s -> %s: worst sensor has %d of %d hours, fetching", d_from, d_to, worst, possible)
            run_ingest(conn, f"{d_from}T00:00:00Z", f"{d_to}T00:00:00Z", mode="backfill")
            conn.commit()   # this month is now safe even if the next one dies

    log.info("backfill done")


if __name__ == "__main__":
    main()