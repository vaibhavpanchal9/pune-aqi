"""Day 2. The job that runs every hour, forever.

    python ingest.py --discover            # refresh the station registry (run first, then monthly)
    python ingest.py                       # normal hourly run: last 6 hours
    python ingest.py --hours-back 48       # catch up after downtime
    python ingest.py --from 2024-01-01 --to 2024-02-01    # backfill (Day 5)

Note that live ingestion and backfill are the same code path with different
dates. That is a consequence of OpenAQ v3 exposing /sensors/{id}/hours with a
date range, and it means you do not have to write a second downloader.

Why it asks for the last 6 hours rather than just the last 1:
stations publish late. A reading for 14:00 might not appear until 16:30.
Asking for a window and letting the primary key throw away what we already
have is far simpler, and far more correct, than trying to be clever about
exactly which hour is due.
"""

import sys
import time
import logging
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import (get_conn, insert_measurements, upsert_locations_and_sensors,
                upsert_sensor_detail, start_run, finish_run)
from openaq_client import (get_pune_locations, get_location_sensors,
                           iter_sensor_hours, OpenAQError, SLEEP_BETWEEN_CALLS)
from transform import (flatten_locations, flatten_location_sensors,
                       flatten_hours)

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ingest.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ingest")


def discover(conn):
    """Find Pune's PM2.5 stations, then fetch each sensor's real date range.

    The second pass matters. /v3/locations gives a station's overall dates,
    which are the union across every sensor it has ever held. Several Pune
    stations hold a sensor that died in mid-2022 and a replacement that
    started in Feb 2025 -- at location level that reads as five unbroken
    years, when in fact there is a 2.5 year hole in the middle.
    Only /v3/locations/{id}/sensors exposes that.
    """
    log.info("pass 1: finding stations near Pune")
    locations = flatten_locations(get_pune_locations(parameters_id=2))
    n_loc, n_sensor = upsert_locations_and_sensors(conn, locations)
    log.info("  %d locations, %d sensors registered", n_loc, n_sensor)

    log.info("pass 2: fetching per-sensor dates (%d requests)", len(locations))
    total = 0
    for loc in locations:
        try:
            payload = get_location_sensors(loc["location_id"])
            rows = flatten_location_sensors(payload, loc["location_id"])
            total += upsert_sensor_detail(conn, rows)
        except OpenAQError as exc:
            log.warning("  location %s failed: %s", loc["location_id"], exc)
        time.sleep(SLEEP_BETWEEN_CALLS)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sensors "
                    "WHERE parameter = 'pm25' AND is_active")
        n_active = cur.fetchone()[0]
    log.info("  %d sensor records updated, %d live pm25 sensors", total, n_active)
    return n_loc, n_active


def active_sensors(conn, parameter="pm25"):
    """Sensor ids worth polling: live, and one per station.

    Two filters, both necessary.

    is_active drops sensors that stopped reporting -- polling a sensor that
    died in 2022 costs a request per hour forever and returns nothing.

    DISTINCT ON (location_id) drops the duplicates. Four Pune stations expose
    two pm25 sensors: a retired one and its replacement. Ingesting both would
    give two series for one physical place, which the database accepts happily
    because the sensor ids differ, and which only shows up in Week 2 as
    doubled feature rows.

    Ordering by observed_count keeps the better-covered sensor when a station
    somehow has two live ones.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (s.location_id)
                      s.sensor_id, l.name
               FROM sensors s
               JOIN locations l ON l.location_id = s.location_id
               WHERE s.parameter = %s AND s.is_active
               ORDER BY s.location_id,
                        s.observed_count DESC NULLS LAST,
                        s.datetime_last DESC NULLS LAST""",
            (parameter,),
        )
        return cur.fetchall()


def run_ingest(conn, datetime_from, datetime_to, mode):
    """Pull hourly data for every sensor in the window and save it."""
    run_id = start_run(conn, source="openaq", mode=mode)
    sensors = active_sensors(conn)

    if not sensors:
        finish_run(conn, run_id, "failed",
                   error_text="No sensors in registry. Run with --discover first.")
        log.error("no sensors registered. Run: python ingest.py --discover")
        return 0, 0

    total_fetched = total_inserted = 0
    failures = []

    for sensor_id, station_name in sensors:
        try:
            for payload in iter_sensor_hours(sensor_id, datetime_from, datetime_to):
                rows = flatten_hours(payload, sensor_id)
                total_fetched += len(rows)
                total_inserted += insert_measurements(conn, rows)
        except OpenAQError as exc:
            # One dead sensor must not kill the whole run. Log it, carry on.
            failures.append(f"sensor {sensor_id} ({station_name}): {exc}")
            log.warning("sensor %s failed: %s", sensor_id, exc)

    status = "ok" if not failures else ("failed" if len(failures) == len(sensors) else "partial")
    finish_run(conn, run_id, status,
               sensors_tried=len(sensors),
               rows_fetched=total_fetched,
               rows_inserted=total_inserted,
               error_text="; ".join(failures)[:2000] or None)

    log.info("%s run finished: %d sensors, %d rows seen, %d new, status=%s",
             mode, len(sensors), total_fetched, total_inserted, status)
    return total_fetched, total_inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true",
                    help="refresh the station registry, then exit")
    ap.add_argument("--hours-back", type=int, default=6,
                    help="how far back to ask for (default 6)")
    ap.add_argument("--from", dest="date_from", help="backfill start, YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", help="backfill end, YYYY-MM-DD")
    args = ap.parse_args()

    with get_conn() as conn:
        if args.discover:
            discover(conn)
            return

        if args.date_from and args.date_to:
            mode = "backfill"
            dt_from = f"{args.date_from}T00:00:00Z"
            dt_to = f"{args.date_to}T00:00:00Z"
        else:
            mode = "live"
            now = datetime.now(timezone.utc)
            dt_from = (now - timedelta(hours=args.hours_back)).strftime("%Y-%m-%dT%H:00:00Z")
            dt_to = now.strftime("%Y-%m-%dT%H:00:00Z")

        log.info("%s ingest, window %s to %s", mode, dt_from, dt_to)
        run_ingest(conn, dt_from, dt_to, mode)


if __name__ == "__main__":
    main()
