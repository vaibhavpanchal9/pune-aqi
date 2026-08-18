"""Database connection. One place that knows how to reach Postgres."""

import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    """Open a connection to Postgres using credentials from .env.

    Returns a psycopg2 connection. The caller is responsible for closing it,
    which is why every use below is wrapped in a `with` block.
    """
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "aqi"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
    )


def insert_measurements(conn, rows):
    """Insert measurement rows, silently skipping ones we already have.

    rows: list of dicts with keys sensor_id, measured_at, value, source
    Returns the number of rows actually inserted (not the number offered).

    ON CONFLICT DO NOTHING is what makes this safe to run repeatedly.
    If the row already exists, Postgres skips it instead of raising.
    RETURNING gives us back only the rows that were genuinely new, so the
    count we log is the truth rather than just len(rows).
    """
    if not rows:
        return 0

    sql = """
        INSERT INTO measurements (sensor_id, measured_at, value, source)
        VALUES %s
        ON CONFLICT (sensor_id, measured_at, source) DO NOTHING
        RETURNING sensor_id
    """
    values = [(r["sensor_id"], r["measured_at"], r["value"], r["source"]) for r in rows]

    with conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=1000)
        inserted = len(cur.fetchall())
    conn.commit()
    return inserted


def upsert_locations_and_sensors(conn, locations):
    """Save the station registry. Safe to re-run: updates what changed.

    locations: list of dicts from transform.flatten_locations()
    """
    loc_sql = """
        INSERT INTO locations (location_id, name, locality, timezone, latitude,
                               longitude, provider, is_mobile, is_monitor,
                               datetime_first, datetime_last)
        VALUES %s
        ON CONFLICT (location_id) DO UPDATE SET
            datetime_last = EXCLUDED.datetime_last,
            last_checked  = now()
    """
    sensor_sql = """
        INSERT INTO sensors (sensor_id, location_id, parameter, units)
        VALUES %s
        ON CONFLICT (sensor_id) DO NOTHING
    """

    loc_values, sensor_values = [], []
    for loc in locations:
        loc_values.append((
            loc["location_id"], loc["name"], loc["locality"], loc["timezone"],
            loc["latitude"], loc["longitude"], loc["provider"],
            loc["is_mobile"], loc["is_monitor"],
            loc["datetime_first"], loc["datetime_last"],
        ))
        for s in loc["sensors"]:
            sensor_values.append((
                s["sensor_id"], loc["location_id"], s["parameter"], s["units"]
            ))

    with conn.cursor() as cur:
        if loc_values:
            execute_values(cur, loc_sql, loc_values)
        if sensor_values:
            execute_values(cur, sensor_sql, sensor_values)
    conn.commit()
    return len(loc_values), len(sensor_values)


def start_run(conn, source, mode):
    """Record that a run began. Returns the run id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_runs (source, mode, status) "
            "VALUES (%s, %s, 'running') RETURNING id",
            (source, mode),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn, run_id, status, sensors_tried=0, rows_fetched=0,
               rows_inserted=0, error_text=None):
    """Close out a run row. Always call this, including on failure."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ingestion_runs
               SET finished_at = now(), status = %s, sensors_tried = %s,
                   rows_fetched = %s, rows_inserted = %s, error_text = %s
               WHERE id = %s""",
            (status, sensors_tried, rows_fetched, rows_inserted,
             error_text, run_id),
        )
    conn.commit()


if __name__ == "__main__":
    # Day 1, task 10. The smoke test.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            print(cur.fetchone()[0])
