"""Step 17. When the model loses, which way is it wrong?

    python error_direction.py        # -> results/error_direction.csv

Step 8 found WHERE the ridge loses to "same as now": in the winter test window and in hours above
90 µg/m³. It did not say WHY. This script looks at the direction of the errors on the same out-of-sample
forecasts (band_weekly.out_of_sample: same ridge, same folds, same rows), cut four ways:

  1. by how polluted the air TURNED OUT to be             what someone using the forecast experiences
  2. by how polluted the air was WHEN THE FORECAST WAS MADE   what the model knew at the time
  3. the same as 2, for the winter window alone
  4. the bad-air hours split in two: was the air already above 90 a day earlier, or not yet?

A warning that belongs with table 1. Picking hours by their OUTCOME makes any forecaster look too low
on the high ones and too high on the low ones: no forecast can know in advance which hours will be the
extreme ones. Table 1 shows how big the miss is. Tables 2 to 4 are the fair test of why, because they
sort the hours by something that was known when the forecast was made.

Columns:
  now            mean reading when the forecast was made (this is also persistence's forecast)
  forecast       mean ridge forecast for 24 hours later
  actual         mean reading 24 hours later
  bias_*         mean of (forecast - actual). Negative = the forecasts ran low.
  too_low_*      share of forecasts that were below the actual
  mae_*          mean absolute error
"""

from pathlib import Path

import numpy as np
import pandas as pd

from band_weekly import out_of_sample
from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from error_analysis import BANDS, label
from splits import walk_forward

BAD_AIR = 90          # µg/m³: where Step 8's "Poor or worse" band starts
WINTER_FOLD = 1       # the oldest test window, 11 Dec to 3 Feb
COLUMNS = ["segment", "n", "now", "forecast", "actual", "bias_ridge", "bias_persistence",
           "too_low_ridge", "too_low_persistence", "mae_ridge", "mae_persistence"]


def with_levels(oos):
    """Two labels per forecast, using Step 8's bands: the level that came, and the level at the time."""
    out = oos.copy()
    out["outcome_level"] = [label(v, BANDS) for v in out["y"]]
    out["origin_level"] = [label(v, BANDS) for v in out["persistence"]]
    return out


def direction_table(df, by):
    """One row per group of `by`: the means, and for the ridge and for persistence the bias, the share of
    forecasts that were too low, and the MAE."""
    rows = []
    for key, g in df.groupby(by, sort=True):
        ridge, same = g["point"] - g["y"], g["persistence"] - g["y"]
        rows.append({"segment": str(key), "n": int(len(g)),
                     "now": g["persistence"].mean(), "forecast": g["point"].mean(), "actual": g["y"].mean(),
                     "bias_ridge": ridge.mean(), "bias_persistence": same.mean(),
                     "too_low_ridge": (ridge < 0).mean(), "too_low_persistence": (same < 0).mean(),
                     "mae_ridge": ridge.abs().mean(), "mae_persistence": same.abs().mean()})
    return pd.DataFrame(rows, columns=COLUMNS)          # the columns are there even if no hour qualifies


def bad_air_split(df, threshold=BAD_AIR):
    """The hours that turned out at or above `threshold`, split by whether the air was already there a day
    earlier. 'Already' hours are a bad spell going on; 'not yet' hours are a bad spell arriving."""
    bad = df[df["y"] >= threshold].copy()
    bad["a_day_earlier"] = np.where(bad["persistence"] >= threshold,
                                    f"1 already at {threshold} or more", f"2 still under {threshold}")
    return direction_table(bad, "a_day_earlier")


def show(title, table):
    print(f"\n{title}")
    shown = table.copy()
    for c in ("now", "forecast", "actual", "bias_ridge", "bias_persistence", "mae_ridge", "mae_persistence"):
        shown[c] = shown[c].round(1)
    for c in ("too_low_ridge", "too_low_persistence"):
        shown[c] = shown[c].round(2)
    print(shown.to_string(index=False))


def main():
    f = usable(load_features(PRIMARY))
    folds = walk_forward(f.index)
    df = with_levels(out_of_sample(f, folds, feature_columns(f)))
    ridge_mae = (df["point"] - df["y"]).abs().mean()
    same_mae = (df["persistence"] - df["y"]).abs().mean()
    pd.set_option("display.width", 220)
    print(f"sensor {PRIMARY} · {len(df):,} out-of-sample forecasts · overall MAE ridge {ridge_mae:.2f} "
          f"vs persistence {same_mae:.2f} (must be Step 8's two numbers) · bias ridge "
          f"{(df['point'] - df['y']).mean():+.2f}, persistence {(df['persistence'] - df['y']).mean():+.2f}")

    tables = {
        "1 by the level that came": direction_table(df, "outcome_level"),
        "2 by the level when the forecast was made": direction_table(df, "origin_level"),
        "3 winter window only, by the level when the forecast was made":
            direction_table(df[df["fold"] == WINTER_FOLD], "origin_level"),
        f"4 hours that turned out at {BAD_AIR} or more, by the level a day earlier": bad_air_split(df),
    }
    for title, table in tables.items():
        show(title, table)

    Path("results").mkdir(exist_ok=True)
    out = pd.concat([t.assign(table=title) for title, t in tables.items()], ignore_index=True)
    out.insert(0, "table", out.pop("table"))
    out.to_csv("results/error_direction.csv", index=False)
    print("\nwritten: results/error_direction.csv")


if __name__ == "__main__":
    main()
