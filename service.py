"""Step 10 (3/3), part a. The queries behind the API: one function per endpoint, plain dicts out.

    python service.py            # prints what /health, /forecast and /stats would return, no server needed

Kept apart from app.py so that (1) the route layer can be tested with fake data and no database, and
(2) the same numbers can be printed from a terminal when something looks wrong. Every function opens
one connection, runs its queries, and closes it: a connection per request. Neon's free tier sleeps
when idle, so the first request after a quiet spell can take a second; a pool is a v2 item.

The served sensor, the model version and the walk-forward figures are read from the model file, so
the API cannot drift from what forecast.py writes.
"""

import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from db import get_conn
from healthcheck import STALE_HOURS, UPSTREAM_HOURS

MODEL_PATH = Path(__file__).resolve().parent / "models" / "v1.json"
SPEC = json.loads(MODEL_PATH.read_text())
SENSOR = int(SPEC["sensor_id"])
MODEL_VERSION = SPEC["version"]
HORIZON = int(SPEC["horizon_hours"])

IST = "Asia/Kolkata"


def _hours(delta):
    return None if delta is None else round(delta.total_seconds() / 3600, 1)


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


# ----------------------------------------------------------------------------- /health
def health():
    now = datetime.now(timezone.utc)
    with closing(get_conn()) as conn, conn.cursor() as cur:
        newest, = _one(cur, "SELECT max(measured_at) FROM measurements WHERE sensor_id = %s AND source = 'openaq'",
                       (SENSOR,))
        last_ok, runs_24h = _one(cur, """
            SELECT max(run_at) FILTER (WHERE status IN ('ok', 'partial')),
                   count(*)    FILTER (WHERE status IN ('ok', 'partial') AND run_at > now() - interval '24 hours')
            FROM ingestion_runs""")
        ahead, newest_target, last_issued = _one(cur, """
            SELECT count(*) FILTER (WHERE target_time > now()), max(target_time), max(issued_at)
            FROM forecasts WHERE sensor_id = %s AND model_version = %s""", (SENSOR, MODEL_VERSION))

    since_run = _hours(None if last_ok is None else now - last_ok)
    since_reading = _hours(None if newest is None else now - newest)
    pipeline_ok = since_run is not None and since_run < STALE_HOURS
    upstream_ok = since_reading is not None and since_reading < UPSTREAM_HOURS
    status = "broken" if not pipeline_ok else ("ok" if upstream_ok else "upstream_lag")
    return {
        "status": status,
        "checked_at": now,
        "pipeline": {"last_ok_run": last_ok, "hours_since_ok_run": since_run, "runs_last_24h": int(runs_24h),
                     "stale_after_hours": STALE_HOURS},
        "data": {"sensor_id": SENSOR, "newest_reading": newest, "hours_since_newest": since_reading,
                 "upstream_lag_after_hours": UPSTREAM_HOURS},
        "forecasts": {"model_version": MODEL_VERSION, "hours_ahead_on_file": int(ahead),
                      "newest_target": newest_target, "last_issued": last_issued},
    }


# ----------------------------------------------------------------------------- /forecast
def station_name(cur, sensor_id):
    row = _one(cur, """
        SELECT l.name FROM sensors s JOIN locations l ON l.location_id = s.location_id
        WHERE s.sensor_id = %s""", (sensor_id,))
    return None if row is None else row[0]


def forecast(sensor_id=SENSOR):
    """The forecasts on file for hours still ahead, oldest target first. Empty list when none."""
    with closing(get_conn()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT target_time, point, lower, upper, issued_at, origin_time
            FROM forecasts
            WHERE sensor_id = %s AND model_version = %s AND target_time > now()
            ORDER BY target_time""", (sensor_id, MODEL_VERSION))
        rows = cur.fetchall()
        station = station_name(cur, sensor_id)
    return {
        "sensor_id": sensor_id,
        "station": station,
        "model_version": MODEL_VERSION,
        "horizon_hours": HORIZON,
        "band": f"{SPEC['band']['nominal_coverage']:.0%} interval ({SPEC['band']['method']})",
        "data_as_of": max((r[5] for r in rows), default=None),
        "forecasts": [{"target_time": r[0], "point": r[1], "lower": r[2], "upper": r[3], "issued_at": r[4]}
                      for r in rows],
    }


# ----------------------------------------------------------------------------- /stats
def stats(sensor_id=SENSOR):
    """Live accuracy so far, lead time, availability, and the walk-forward figures from the model file."""
    with closing(get_conn()) as conn, conn.cursor() as cur:
        scored, mae, bias, cov, width, pers, first, last = _one(cur, """
            SELECT count(*),
                   avg(abs(f.point - m.value)),
                   avg(f.point - m.value),
                   avg((m.value BETWEEN f.lower AND f.upper)::int),
                   avg(f.upper - f.lower),
                   avg(abs(o.value - m.value)),
                   min(f.target_time), max(f.target_time)
            FROM forecasts f
            JOIN measurements m
              ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
            LEFT JOIN measurements o
              ON o.sensor_id = f.sensor_id AND o.measured_at = f.origin_time AND o.source = 'openaq'
            WHERE f.sensor_id = %s AND f.model_version = %s
              AND m.value > 0 AND m.value < 985""", (sensor_id, MODEL_VERSION))
        n, delay, lead, min_lead = _one(cur, """
            SELECT count(*),
                   avg(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600),
                   avg(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600),
                   min(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)
            FROM forecasts WHERE sensor_id = %s AND model_version = %s""", (sensor_id, MODEL_VERSION))
        with_fc, = _one(cur, """
            SELECT count(*) FROM forecasts
            WHERE sensor_id = %s AND model_version = %s
              AND target_time > now() - interval '7 days' AND target_time <= now()""", (sensor_id, MODEL_VERSION))

    r = lambda x, d=2: None if x is None else round(float(x), d)
    return {
        "sensor_id": sensor_id,
        "model_version": MODEL_VERSION,
        "live": {"scored_hours": int(scored), "mae": r(mae), "bias": r(bias), "coverage_80": r(cov, 3),
                 "mean_width": r(width, 1), "persistence_mae": r(pers),
                 "first_scored": first, "last_scored": last,
                 "note": "forecasts whose target hour now has a reading, scored as issued; never revised"},
        "lead_time": {"forecasts_issued": int(n), "mean_issue_delay_hours": r(delay, 1),
                      "mean_lead_hours": r(lead, 1), "min_lead_hours": r(min_lead, 1)},
        "availability_7d": {"hours_with_forecast": int(with_fc), "hours": 168, "share": r(with_fc / 168, 3)},
        "walk_forward": SPEC.get("walk_forward"),
        "trained_on": SPEC["trained_on"],
    }


if __name__ == "__main__":
    for name, fn in [("/health", health), ("/forecast", forecast), ("/stats", stats)]:
        print(f"\n{name}")
        print(json.dumps(fn(), indent=2, default=str))
