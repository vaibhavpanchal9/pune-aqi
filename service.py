"""Step 10 (3/3), part a. The queries behind the API: one function per endpoint, plain dicts out.

    python service.py            # prints what /health, /forecast and /stats would return, no server needed

Kept apart from app.py so that (1) the route layer can be tested with fake data and no database, and
(2) the same numbers can be printed from a terminal when something looks wrong. Every function opens
one connection, runs its queries, and closes it: a connection per request. Neon's free tier sleeps
when idle, so the first request after a quiet spell can take a second; a pool is a later item.

The served sensor, the model version, the tiers and the walk-forward figures are read from the model
file (modelfile.py), so the API cannot drift from what forecast.py writes.
"""

import json
from contextlib import closing
from datetime import datetime, timezone

from db import get_conn
from healthcheck import STALE_HOURS, UPSTREAM_HOURS
from modelfile import DEFAULT_MODEL, load_model, tiers_of

SPEC = load_model(DEFAULT_MODEL)
TIERS = tiers_of(SPEC)
SENSOR = int(SPEC["sensor_id"])
MODEL_VERSION = SPEC["version"]
HORIZON = int(SPEC["horizon_hours"])
BAND = TIERS[0]["band"]

# forecast f scored against the reading m at its target hour; o is the reading at its origin hour,
# i.e. what "same as 24 hours ago" would have said. The actual is kept only if the value policy keeps it.
SCORED = """
    FROM forecasts f
    JOIN measurements m
      ON m.sensor_id = f.sensor_id AND m.measured_at = f.target_time AND m.source = 'openaq'
    LEFT JOIN measurements o
      ON o.sensor_id = f.sensor_id AND o.measured_at = f.origin_time AND o.source = 'openaq'
    WHERE f.sensor_id = %s AND m.value > 0 AND m.value < 985
"""
SCORE_COLUMNS = """
    count(*),
    avg(abs(f.point - m.value)),
    avg(f.point - m.value),
    avg((m.value BETWEEN f.lower AND f.upper)::int),
    avg(f.upper - f.lower),
    avg(abs(o.value - m.value)),
    min(f.target_time), max(f.target_time)
"""


def _hours(delta):
    return None if delta is None else round(delta.total_seconds() / 3600, 1)


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


def _r(x, digits=2):
    return None if x is None else round(float(x), digits)


def _score(row):
    """A SCORE_COLUMNS row as a dict."""
    scored, mae, bias, cov, width, pers, first, last = row
    return {"scored_hours": int(scored), "mae": _r(mae), "bias": _r(bias), "coverage_80": _r(cov, 3),
            "mean_width": _r(width, 1), "persistence_mae": _r(pers), "first_scored": first, "last_scored": last}


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
            SELECT target_time, point, lower, upper, issued_at, origin_time, tier
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
        "band": f"{BAND['nominal_coverage']:.0%} interval ({BAND['method']})",
        "data_as_of": max((r[5] for r in rows), default=None),
        "forecasts": [{"target_time": r[0], "point": r[1], "lower": r[2], "upper": r[3], "issued_at": r[4],
                       "tier": r[6]} for r in rows],
    }


# ----------------------------------------------------------------------------- /stats
def stats(sensor_id=SENSOR):
    """Live accuracy (this version, per tier, and per version), lead time, availability, walk-forward."""
    with closing(get_conn()) as conn, conn.cursor() as cur:
        live = _score(_one(cur, f"SELECT {SCORE_COLUMNS} {SCORED} AND f.model_version = %s",
                           (sensor_id, MODEL_VERSION)))
        cur.execute(f"SELECT f.tier, {SCORE_COLUMNS} {SCORED} AND f.model_version = %s GROUP BY f.tier ORDER BY f.tier",
                    (sensor_id, MODEL_VERSION))
        by_tier = [{"tier": row[0], **_score(row[1:])} for row in cur.fetchall()]
        cur.execute(f"SELECT f.model_version, {SCORE_COLUMNS} {SCORED} GROUP BY f.model_version "
                    f"ORDER BY f.model_version", (sensor_id,))
        by_version = [{"model_version": row[0], **_score(row[1:])} for row in cur.fetchall()]
        n, delay, lead, min_lead = _one(cur, """
            SELECT count(*),
                   avg(EXTRACT(EPOCH FROM (issued_at - origin_time)) / 3600),
                   avg(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600),
                   min(EXTRACT(EPOCH FROM (target_time - issued_at)) / 3600)
            FROM forecasts WHERE sensor_id = %s AND model_version = %s""", (sensor_id, MODEL_VERSION))
        with_fc, = _one(cur, """
            SELECT count(DISTINCT target_time) FROM forecasts
            WHERE sensor_id = %s AND target_time > now() - interval '7 days' AND target_time <= now()""",
                        (sensor_id,))

    live["note"] = "forecasts whose target hour now has a reading, scored as issued; never revised"
    return {
        "sensor_id": sensor_id,
        "model_version": MODEL_VERSION,
        "live": live,
        "live_by_tier": by_tier,
        "live_by_version": by_version,
        "lead_time": {"forecasts_issued": int(n), "mean_issue_delay_hours": _r(delay, 1),
                      "mean_lead_hours": _r(lead, 1), "min_lead_hours": _r(min_lead, 1)},
        "availability_7d": {"hours_with_forecast": int(with_fc), "hours": 168, "share": _r(with_fc / 168, 3)},
        "tiers": [{"name": t["name"], "features": len(t["features"]), "needs_hours": t.get("needs_hours"),
                   "walk_forward": t.get("walk_forward")} for t in TIERS],
        "walk_forward": SPEC.get("cascade") or SPEC.get("walk_forward"),
        "trained_on": TIERS[0]["trained_on"],
    }


if __name__ == "__main__":
    for name, fn in [("/health", health), ("/forecast", forecast), ("/stats", stats)]:
        print(f"\n{name}")
        print(json.dumps(fn(), indent=2, default=str))
