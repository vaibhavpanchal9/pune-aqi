"""Step 6 (1/2). The data as the model sees it.

    python dataset.py                     # primary station -> data/features_12238693.csv, prints a summary
    python dataset.py --sensor 12236443   # another station

What happens, in order (each step is a small function, each is tested in tests/test_target.py):

  load_readings     raw hourly readings for one sensor, straight from the measurements table
  clean_values      the VALUE POLICY (decisions.md, 2026-10-30): negatives, zeros, >= 985, runs of 6+
                    identical values, and 4x spikes/dropouts become missing. Nothing is edited.
  to_grid           one row per hour from the first reading to the last; missing hours are NaN
  fill_short_gaps   the GAP POLICY: a gap of at most 3 consecutive missing hours is forward-filled;
                    longer gaps stay missing. (pandas' ffill(limit=3) would fill the first 3 hours of a
                    long gap too -- that is NOT the policy, so the fill is done by run length.)
  make_features     lags, rolling means with their counts, IST time features, cyclical encodings,
                    and the target y = the UNFILLED clean value 24 hours later. The target is never filled.

Rows == hours on the grid, so shift(24) means 24 hours. That is the whole reason for the grid.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from db import get_conn

PRIMARY = 12238693
IST = "Asia/Kolkata"
LAGS = (1, 2, 3, 6, 12, 24, 48, 144, 168)   # 144 = one week before the 24 h-ahead target
MAX_FILL = 3                 # hours; the gap policy
HORIZON = 24                 # hours ahead


# ----------------------------------------------------------------------------- loading
def load_readings(sensor_id):
    """Raw readings for one sensor as a Series indexed by UTC hour, sorted."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT measured_at, value FROM measurements "
                    "WHERE sensor_id = %(sid)s AND source = 'openaq' ORDER BY measured_at",
                    {"sid": sensor_id})
        rows = cur.fetchall()
    ts = pd.to_datetime([r[0] for r in rows], utc=True)
    s = pd.Series([float(r[1]) for r in rows], index=pd.DatetimeIndex(ts), name="value")
    return s[~s.index.duplicated(keep="first")].sort_index()


# ----------------------------------------------------------------------------- value policy
def clean_values(s, flat_run=6, ratio=4.0):
    """Apply the value policy. Returns (cleaned Series with NaN where removed, dict of counts per rule).

    `s` is the raw reading series (only hours that exist). Neighbours for the spike/dropout rule are the
    previous and next READING, exactly as quality_report.py counts them, so the counts match the audit.
    """
    v = s.astype(float)
    counts = {}

    negative = v < 0
    zero = v == 0
    ceiling = v >= 985

    # runs of identical consecutive values (gaps-and-islands, same idea as quality_report.py section D)
    new_run = (v != v.shift()).cumsum()
    run_len = v.groupby(new_run).transform("size")
    flat = run_len >= flat_run

    prev, nxt = v.shift(1), v.shift(-1)
    both = (prev > 0) & (nxt > 0)
    spike = both & (v > ratio * prev) & (v > ratio * nxt)
    dropout = both & (v > 0) & (v < prev / ratio) & (v < nxt / ratio)

    for name, mask in [("negative", negative), ("zero", zero), ("ceiling_985plus", ceiling),
                       ("flat_run_6plus", flat), ("spike_4x", spike), ("dropout_4x", dropout)]:
        counts[name] = int(mask.sum())
    remove = negative | zero | ceiling | flat | spike | dropout
    counts["removed_total"] = int(remove.sum())
    counts["readings"] = int(len(v))
    return v.mask(remove), counts


# ----------------------------------------------------------------------------- grid + gap policy
def to_grid(s):
    """One row per hour between the first and last timestamp. Missing hours become NaN."""
    return s.asfreq("h")


def fill_short_gaps(s, max_gap=MAX_FILL):
    """Forward-fill only gaps of at most `max_gap` consecutive missing hours.

    Returns (filled Series, boolean Series 'was_filled').
    """
    isna = s.isna()
    run_id = (isna != isna.shift()).cumsum()
    run_len = isna.groupby(run_id).transform("size")
    fillable = isna & (run_len <= max_gap)
    # a gap at the very start has nothing to carry forward; ffill leaves it NaN, which is correct
    filled = s.where(~fillable, s.ffill())
    was_filled = fillable & filled.notna()
    return filled, was_filled


# ----------------------------------------------------------------------------- features
def make_features(filled, clean, horizon=HORIZON, lags=LAGS):
    """Features from the FILLED series; target from the UNFILLED clean series, `horizon` hours later.

    Everything a row knows is at or before its own timestamp: lags shift forward in time, rolling
    windows end at the current hour. The only thing that looks into the future is y, on purpose.
    """
    f = pd.DataFrame(index=filled.index)
    f["value"] = filled
    for k in lags:
        f[f"lag_{k}"] = filled.shift(k)
    f["roll_24"] = filled.rolling(24, min_periods=1).mean()
    f["n_24"] = filled.rolling(24, min_periods=1).count()
    f["roll_168"] = filled.rolling(168, min_periods=1).mean()
    f["n_168"] = filled.rolling(168, min_periods=1).count()

    local = filled.index.tz_convert(IST)
    f["hour_ist"] = local.hour
    f["dow_ist"] = local.dayofweek              # Monday = 0
    f["month_ist"] = local.month
    doy = local.dayofyear
    f["hour_sin"] = np.sin(2 * np.pi * f["hour_ist"] / 24)
    f["hour_cos"] = np.cos(2 * np.pi * f["hour_ist"] / 24)
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    f["y"] = clean.shift(-horizon)              # the value `horizon` hours later, never filled
    return f


def feature_columns(f):
    """The columns a model is allowed to see (everything except the target and bookkeeping)."""
    return [c for c in f.columns if c not in ("y", "was_filled")]


def usable(f):
    """Rows where every feature and the target exist."""
    return f.dropna(subset=feature_columns(f) + ["y"])


def build(sensor_id):
    """The whole pipeline for one sensor. Returns (features DataFrame, dict of counts)."""
    raw = load_readings(sensor_id)
    clean, counts = clean_values(raw)
    grid = to_grid(clean)
    filled, was_filled = fill_short_gaps(grid)
    f = make_features(filled, grid)
    f["was_filled"] = was_filled
    counts.update({
        "grid_hours": int(len(grid)),
        "hours_missing_after_cleaning": int(grid.isna().sum()),
        "hours_filled": int(was_filled.sum()),
        "hours_still_missing": int(filled.isna().sum()),
        "usable_rows": int(len(usable(f))),
    })
    return f, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    f, counts = build(args.sensor)
    Path("data").mkdir(exist_ok=True)
    out = Path("data") / f"features_{args.sensor}.csv"
    f.to_csv(out, index_label="ts")

    print(f"sensor {args.sensor}: {f.index.min()} -> {f.index.max()}")
    print(f"shape {f.shape}  (rows = grid hours, columns = features + y + was_filled)")
    print("value policy  :", {k: counts[k] for k in ("readings", "negative", "zero", "ceiling_985plus",
                                                      "flat_run_6plus", "spike_4x", "dropout_4x", "removed_total")})
    print("gap policy    :", {k: counts[k] for k in ("grid_hours", "hours_missing_after_cleaning",
                                                      "hours_filled", "hours_still_missing")})
    print(f"usable rows   : {counts['usable_rows']}  (all features and y present)")
    print(f"written       : {out}")


if __name__ == "__main__":
    main()
