"""Step 6 (2/2). Three (plus one) deliberately simple forecasters, scored on the last 8 weeks.

    python baselines.py                       # reads data/features_12238693.csv, writes results/baselines.csv
    python baselines.py --sensor 12236443 --weeks 8

Every forecaster answers the same question: "what will PM2.5 be 24 hours from now?" using only what
is known at the origin hour t. Each one is a column that already exists in the feature table:

  persistence   yhat = value at t            "tomorrow this hour = now"  (the seasonal-naive for a 24 h horizon)
  weekly_naive  yhat = value at t - 144 h    "tomorrow this hour = the same hour last week"
  mean_24h      yhat = mean of the last 24 h "tomorrow this hour = today's average"
  climatology   yhat = average y for this (month, hour) in the TRAINING rows only

The test window is the last `weeks` weeks of usable rows. The training window for climatology ends
24 hours before the test window starts, so no training target reaches into the test period.

The best of these is THE BENCHMARK. Every model in Step 8 is judged against it, on the same rows.
"""

import argparse
from pathlib import Path

import pandas as pd

from dataset import PRIMARY, usable
from metrics import score

HORIZON = 24


def load_features(sensor_id):
    path = Path("data") / f"features_{sensor_id}.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run: python dataset.py --sensor {sensor_id}")
    f = pd.read_csv(path, index_col="ts", parse_dates=["ts"])
    f.index = pd.DatetimeIndex(pd.to_datetime(f.index, utc=True))
    return f


def split_last_weeks(f, weeks):
    """(train, test): test = the last `weeks` weeks of usable rows; train ends HORIZON hours before it."""
    u = usable(f)
    test_start = u.index.max() - pd.Timedelta(weeks=weeks)
    test = u[u.index > test_start]
    train = u[u.index <= test_start - pd.Timedelta(hours=HORIZON)]
    return train, test


def climatology(train):
    """Mean target per (month, hour) from the training rows. Returns a function of a feature frame."""
    table = train.groupby(["month_ist", "hour_ist"])["y"].mean()

    def predict(frame):
        keys = list(zip(frame["month_ist"], frame["hour_ist"]))
        return pd.Series(table.reindex(keys).to_numpy(), index=frame.index)
    return predict


def forecasters(train):
    return {
        "persistence":  lambda fr: fr["value"],
        "weekly_naive": lambda fr: fr["lag_144"],
        "mean_24h":     lambda fr: fr["roll_24"],
        "climatology":  climatology(train),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args()

    f = load_features(args.sensor)
    train, test = split_last_weeks(f, args.weeks)
    rows = []
    for name, fn in forecasters(train).items():
        s = score(test["y"], fn(test))
        rows.append({"baseline": name, **s})
    out = pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)
    out["sensor_id"] = args.sensor
    out["test_start"] = test.index.min()
    out["test_end"] = test.index.max()
    out["train_rows"] = len(train)

    Path("results").mkdir(exist_ok=True)
    path = Path("results") / "baselines.csv"
    out.to_csv(path, index=False)

    print(f"sensor {args.sensor} · test = last {args.weeks} weeks: {test.index.min()} -> {test.index.max()} "
          f"({len(test)} rows) · train rows {len(train)}")
    print(out[["baseline", "n", "mae", "rmse", "bias"]].round(2).to_string(index=False))
    best = out.iloc[0]
    print(f"\nBENCHMARK: {best['baseline']}  MAE {best['mae']:.2f} µg/m³  — every model must beat this on these rows.")
    print(f"written: {path}")


if __name__ == "__main__":
    main()
