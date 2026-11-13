"""Step 10 (2/3). Issue forecasts: the hourly step that runs after ingest.

    python forecast.py                    # forecast every origin hour of the last 24 h that can be, and has not been
    python forecast.py --dry-run          # compute and print, write nothing
    python forecast.py --model models/v2.json --now 2026-11-12T06:00:00Z

One horizon. For an origin hour t the model gives PM2.5 at t + 24 h, with an 80% band. The row is
written once; a later run never overwrites it (ON CONFLICT DO NOTHING). The table is therefore a log
of what was said and when, and a day later the actual arrives for the same hour: forecast vs actual
is the live accuracy figure (sql/11_forecasts.sql, and /stats in the API).

Tiers (from model version 2). The full model needs every lag back to 168 h; after a hole in the data
longer than 3 h those lags are missing in turn and the full model has no complete row for a day. So the
model file holds the same ridge recipe on shorter lag sets too. For each origin hour this script uses
the RICHEST tier whose features are all present -- "the cascade" -- and records which one in the
`tier` column, so accuracy can be reported per tier. tiers.py is where the tiers are evaluated.

Why the last 24 origin hours and not only the newest: readings reach OpenAQ hours late, sometimes a
day late. The origin hour that could not be forecast at 10:00 because its reading had not arrived is
forecast at 13:00 when it has. A forecast is only issued while its target hour is still in the future.

The product rules on top of the evaluated model live in predict(): point, lower and upper are clipped
at 0, because PM2.5 cannot be negative. Clipping can only move a number towards the actual, so the
walk-forward MAE and the coverage that were measured still hold for what is served.
"""

import argparse

import numpy as np
import pandas as pd

from dataset import load_readings, clean_values, to_grid, fill_short_gaps, make_features
from db import get_conn
from modelfile import DEFAULT_MODEL, load_model, tiers_of

LOOKBACK_DAYS = 14        # readings loaded; the oldest origin considered needs 168 h of history behind it
ORIGIN_WINDOW_H = 24      # origin hours considered per run; older origins have targets in the past anyway

COLUMNS = ["sensor_id", "origin_time", "target_time", "horizon_hours",
           "point", "lower", "upper", "model_version", "tier"]

INSERT = """
INSERT INTO forecasts (sensor_id, origin_time, target_time, horizon_hours, point, lower, upper, model_version, tier)
VALUES %s
ON CONFLICT (sensor_id, target_time, model_version) DO NOTHING
RETURNING target_time
"""


def as_utc(ts):
    """A naive timestamp is taken as UTC; an aware one is converted."""
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


# ----------------------------------------------------------------------------- the model, from numbers
def predict(tier, frame, clip=True):
    """(point, lower, upper) Series for feature rows, from one tier of the JSON model. numpy only.

    point = ((x - mean) / scale) . coef + intercept            -- StandardScaler + Ridge, written out
    band  = point + q * max(point, 1)  for q in (lo_q, hi_q)   -- intervals.residual_band(ratio=True)
    """
    x = frame[tier["features"]].to_numpy(dtype=float)
    z = (x - np.asarray(tier["mean"])) / np.asarray(tier["scale"])
    point = z @ np.asarray(tier["coef"]) + tier["intercept"]
    base = np.maximum(point, 1.0)
    lower = point + tier["band"]["lo_q"] * base
    upper = point + tier["band"]["hi_q"] * base
    if clip:
        point, lower, upper = (np.clip(a, 0.0, None) for a in (point, lower, upper))
    idx = frame.index
    return (pd.Series(point, idx, name="point"), pd.Series(lower, idx, name="lower"),
            pd.Series(upper, idx, name="upper"))


def assign_tiers(frame, tiers):
    """For each row, the name of the richest tier whose features are all present; None if no tier fits.

    `tiers` is richest first. Poorer tiers are written first and overwritten by richer ones.
    """
    chosen = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    for tier in reversed(tiers):
        complete = frame[tier["features"]].notna().all(axis=1)
        chosen[complete] = tier["name"]
    return chosen


# ----------------------------------------------------------------------------- which hours to forecast
def feature_rows(readings):
    """Readings -> feature table, by exactly the training code (dataset.build without the database)."""
    clean, _ = clean_values(readings)
    grid = to_grid(clean)
    filled, _ = fill_short_gaps(grid)
    return make_features(filled, grid)


def issuable(f, now, horizon, tiers, window_h=ORIGIN_WINDOW_H):
    """Origin rows that can be forecast now: recent, target hour still ahead, and some tier complete.

    Returns (rows, tier name per row, counts). The counts are printed, so the hourly log says which
    tier served how many hours and how many had no tier at all.
    """
    recent = f[(f.index > now - pd.Timedelta(hours=window_h)) & (f.index + pd.Timedelta(hours=horizon) > now)]
    chosen = assign_tiers(recent, tiers)
    counts = {"in_window": int(len(recent))}
    counts.update({t["name"]: int((chosen == t["name"]).sum()) for t in tiers})
    counts["none"] = int(chosen.isna().sum())
    keep = chosen.notna()
    return recent[keep], chosen[keep], counts


def forecast_table(spec, f, now):
    """One row per issuable origin, in the shape of the forecasts table. Pure: no database."""
    tiers = tiers_of(spec)
    rows, chosen, counts = issuable(f, now, spec["horizon_hours"], tiers)
    if rows.empty:
        return pd.DataFrame(columns=COLUMNS), counts
    parts = []
    for tier in tiers:
        mine = rows[chosen == tier["name"]]
        if mine.empty:
            continue
        point, lower, upper = predict(tier, mine)
        parts.append(pd.DataFrame({
            "sensor_id": spec["sensor_id"],
            "origin_time": mine.index,
            "target_time": mine.index + pd.Timedelta(hours=spec["horizon_hours"]),
            "horizon_hours": spec["horizon_hours"],
            "point": point.to_numpy(), "lower": lower.to_numpy(), "upper": upper.to_numpy(),
            "model_version": spec["version"],
            "tier": tier["name"],
        }))
    table = pd.concat(parts).sort_values("origin_time").reset_index(drop=True)
    return table[COLUMNS], counts


# ----------------------------------------------------------------------------- writing
def write_rows(conn, table):
    """Insert in one statement; rows already issued are left alone. Returns how many were new."""
    from psycopg2.extras import execute_values
    values = [(int(r.sensor_id), r.origin_time.to_pydatetime(), r.target_time.to_pydatetime(),
               int(r.horizon_hours), float(r.point), float(r.lower), float(r.upper),
               str(r.model_version), str(r.tier))
              for r in table.itertuples(index=False)]
    with conn.cursor() as cur:
        inserted = execute_values(cur, INSERT, values, fetch=True)
    conn.commit()
    return len(inserted)


# ----------------------------------------------------------------------------- the hourly run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    ap.add_argument("--now", default=None, help="pretend it is this UTC time, e.g. 2026-11-12T06:00:00Z")
    args = ap.parse_args()

    spec = load_model(args.model)
    tiers = tiers_of(spec)
    now = as_utc(pd.Timestamp(args.now)) if args.now else pd.Timestamp.now(tz="UTC")
    since = now - pd.Timedelta(days=LOOKBACK_DAYS)
    horizon = spec["horizon_hours"]

    print(f"model          : {spec['version']} for sensor {spec['sensor_id']}, {horizon} h ahead, "
          f"tiers {' > '.join(t['name'] for t in tiers)}, "
          f"trained through {tiers[0]['trained_on']['through'][:16]}")
    readings = load_readings(spec["sensor_id"], since=since.to_pydatetime())
    if readings.empty:
        print(f"readings       : none since {since:%Y-%m-%d %H:%M} UTC -- nothing to forecast")
        return 0
    age_h = (now - readings.index.max()).total_seconds() / 3600
    print(f"readings       : {len(readings)} since {since:%Y-%m-%d %H:%M} UTC, "
          f"newest {readings.index.max():%Y-%m-%d %H:%M} UTC ({age_h:.1f} h old)")

    table, c = forecast_table(spec, feature_rows(readings), now)
    by_tier = ", ".join(f"{t['name']} {c[t['name']]}" for t in tiers)
    print(f"origin hours   : {c['in_window']} in the last {ORIGIN_WINDOW_H} h -> {by_tier}, no tier {c['none']}")
    if table.empty:
        print("nothing to issue this run")
        return 0

    show = table.assign(lead_h=((table["target_time"] - now).dt.total_seconds() / 3600).round(1))
    if args.dry_run:
        pd.set_option("display.width", 160)
        print("\nDRY RUN -- rows that would be written (times UTC):")
        pretty = show.assign(origin_time=show["origin_time"].dt.strftime("%Y-%m-%d %H:%M"),
                             target_time=show["target_time"].dt.strftime("%Y-%m-%d %H:%M"))
        print(pretty[["origin_time", "target_time", "lead_h", "tier", "point", "lower", "upper"]]
              .round(1).to_string(index=False))
        return 0

    conn = get_conn()
    try:
        n = write_rows(conn, table)
    finally:
        conn.close()
    last = show.iloc[-1]
    print(f"written        : {n} new rows ({len(table) - n} already issued)")
    print(f"newest forecast: target {last['target_time']:%Y-%m-%d %H:%M} UTC ({last['lead_h']} h ahead, "
          f"tier {last['tier']})  point {last['point']:.1f}  band [{last['lower']:.1f}, {last['upper']:.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
