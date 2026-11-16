"""Step 11. Copy a slice of the cloud database into the local Postgres started by docker compose.

    docker compose up -d db          # the local database (host port 5433); schema.sql runs on first start
    python seed_local.py             # last 30 days of readings and runs, every sensor, every forecast
    python seed_local.py --days 90

Source: DATABASE_URL from .env (Neon). It is only ever read from.
Target: the compose database, postgresql://aqi:localdev@127.0.0.1:5433/aqi (override with --target).
The target must be on this machine; the script refuses anything else, so it cannot write to the cloud
database by mistake. Rows already present are skipped, so it can be rerun to top up.

The copy is generic: it reads whatever columns each table has, so a new column needs no change here.
"""

import argparse
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

LOCAL_TARGET = "postgresql://aqi:localdev@127.0.0.1:5433/aqi"

# table, optional filter. Order matters: a reading refers to a sensor, a sensor to a location.
TABLES = [
    ("locations", None),
    ("sensors", None),
    ("measurements", "measured_at >= %(since)s"),
    ("ingestion_runs", "run_at >= %(since)s"),
    ("forecasts", None),
]


def is_local(url):
    return urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")


def copy_table(src, dst, table, where, params):
    """Copy the selected rows of one table. Returns (rows read, rows that were new in the target)."""
    with src.cursor() as cur:
        cur.execute(f"SELECT * FROM {table}" + (f" WHERE {where}" if where else ""), params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    with dst.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        before = cur.fetchone()[0]
        if rows:
            # OVERRIDING SYSTEM VALUE lets an id column keep the cloud's ids; it is ignored otherwise
            execute_values(cur, f"INSERT INTO {table} ({', '.join(cols)}) OVERRIDING SYSTEM VALUE VALUES %s "
                                f"ON CONFLICT DO NOTHING", rows, page_size=1000)
        # if a column counts by itself (serial / identity), move its counter past the copied ids
        for col in cols:
            cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, col))
            seq = cur.fetchone()[0]
            if seq:
                cur.execute(f"SELECT setval(%s, greatest((SELECT coalesce(max({col}), 0) FROM {table}), 1))", (seq,))
        cur.execute(f"SELECT count(*) FROM {table}")
        after = cur.fetchone()[0]
    dst.commit()
    return len(rows), after - before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="how many days of readings and runs to copy")
    ap.add_argument("--target", default=LOCAL_TARGET)
    args = ap.parse_args()

    load_dotenv()
    source = os.getenv("DATABASE_URL")
    if not source:
        raise SystemExit("DATABASE_URL is not set (it is read from .env): nothing to copy from")
    if not is_local(args.target):
        raise SystemExit("the target must be a database on this machine (127.0.0.1 / localhost); refusing")
    if is_local(source):
        raise SystemExit("DATABASE_URL points at this machine; expected the cloud database as the source")

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"source : {urlparse(source).hostname} (read only)")
    print(f"target : {urlparse(args.target).hostname}:{urlparse(args.target).port}")
    print(f"window : readings and runs since {since:%Y-%m-%d %H:%M} UTC ({args.days} days); "
          f"sensors, locations and forecasts in full\n")

    src = psycopg2.connect(source)
    src.set_session(readonly=True)
    try:
        dst = psycopg2.connect(args.target)
    except psycopg2.OperationalError as e:
        raise SystemExit(f"cannot reach the local database. Is it running?  docker compose up -d db\n{e}")
    try:
        for table, where in TABLES:
            read, new = copy_table(src, dst, table, where, {"since": since})
            print(f"  {table:<15} read {read:>7,}   new in local {new:>7,}")
    finally:
        src.close()
        dst.close()
    print("\ndone. Try:  curl -s http://127.0.0.1:8000/forecast | python -m json.tool | head -30")


if __name__ == "__main__":
    main()
