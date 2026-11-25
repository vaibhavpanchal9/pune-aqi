"""Step 17. When the model loses, which way is it wrong?

    python error_direction.py        # -> results/error_direction.csv

Step 8 found WHERE the ridge loses to "same as now": in the winter test window and in hours above
90 µg/m³. It did not say WHY. This script looks at the direction of the errors on the same out-of-sample
forecasts (band_weekly.out_of_sample: same ridge, same band, same folds, same rows), cut seven ways:

  1. by how polluted the air TURNED OUT to be                 what someone using the forecast experiences
  2. by how polluted the air was WHEN THE FORECAST WAS MADE   what the model knew at the time
  3. the same as 2, for the winter window alone
  4. the bad-air hours split in two: was the air already at 90 a day earlier, or not yet?
  5. the other side of 4: the forecasts MADE in bad air, split by whether it was still bad a day later
  6. by test window: is the model's level off in one window more than in the others?
  7. the same as 6 with each window's average error taken out: how much of the MAE was that offset?

A warning that belongs with table 1. Picking hours by their OUTCOME makes any forecaster look too low
on the high ones and too high on the low ones: no forecast can know in advance which hours will be the
extreme ones. Table 1 shows how big the miss is. Tables 2 and 3 are the fair test of why, because they
sort the hours by something that was known when the forecast was made. Tables 4 and 5 then split the
bad-air hours by what went before and by what came after, to show when pulling a forecast back towards
the usual level wins and when it loses.

A warning that belongs with table 7. It moves every forecast of a window by that window's own mean error,
and the mean error is only known afterwards. Nobody could have made those forecasts. The table measures
one thing: how much of a window's MAE is a constant offset, and how much is everything else.

Columns:
  now            mean reading when the forecast was made
  forecast       mean ridge forecast for 24 hours later
  actual         mean reading 24 hours later
  bias_*         mean of (forecast - actual). Negative = the forecasts ran low.
  too_low_*      share of forecasts that were below the actual
  mae_*          mean absolute error
  inside_band    share of the actuals inside the ridge's 80% band, the band as it is live

Two numbers here must repeat Step 9 (results/intervals.csv): inside_band in table 6 is the band's coverage
per test window, and in the last row of table 1 its coverage in the bad-air hours (Step 9 counts the hours
above 90, this table the hours at 90 or more: the same hours unless a reading is exactly 90).
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
           "too_low_ridge", "too_low_persistence", "mae_ridge", "mae_persistence", "inside_band"]


def with_levels(oos):
    """What the tables need, added to the out-of-sample rows:

    now             the reading when the forecast was made. The same number as persistence's forecast, kept
                    in a column of its own because table 7 moves the forecasts and must not move this.
    outcome_level   the level that came, in Step 8's bands
    origin_level    the level when the forecast was made, in the same bands
    window          the test window, "window 1 (winter)" to "window 6"
    """
    out = oos.copy()
    out["now"] = out["persistence"]
    out["outcome_level"] = [label(v, BANDS) for v in out["y"]]
    out["origin_level"] = [label(v, BANDS) for v in out["now"]]
    out["window"] = [f"window {int(k)}" + (" (winter)" if k == WINTER_FOLD else "") for k in out["fold"]]
    return out


def direction_table(df, by):
    """One row per group of `by`: the means, and for the ridge and for persistence the bias, the share of
    forecasts that were too low, and the MAE. Last column: the share of actuals inside the ridge's band."""
    rows = []
    for key, g in df.groupby(by, sort=True):
        ridge, same = g["point"] - g["y"], g["persistence"] - g["y"]
        inside = (g["y"] >= g["lower"]) & (g["y"] <= g["upper"])
        rows.append({"segment": str(key), "n": int(len(g)),
                     "now": g["now"].mean(), "forecast": g["point"].mean(), "actual": g["y"].mean(),
                     "bias_ridge": ridge.mean(), "bias_persistence": same.mean(),
                     "too_low_ridge": (ridge < 0).mean(), "too_low_persistence": (same < 0).mean(),
                     "mae_ridge": ridge.abs().mean(), "mae_persistence": same.abs().mean(),
                     "inside_band": inside.mean()})
    return pd.DataFrame(rows, columns=COLUMNS)          # the columns are there even if no hour qualifies


def bad_air_split(df, threshold=BAD_AIR):
    """The hours that turned out at or above `threshold`, split by whether the air was already there a day
    earlier. 'Already' hours are a bad spell going on; 'not yet' hours are a bad spell arriving."""
    bad = df[df["y"] >= threshold].copy()
    bad["a_day_earlier"] = np.where(bad["now"] >= threshold,
                                    f"1 already at {threshold} or more", f"2 still under {threshold}")
    return direction_table(bad, "a_day_earlier")


def bad_now_split(df, threshold=BAD_AIR):
    """The forecasts made when the air was at or above `threshold`, split by whether it was still there a
    day later. bad_air_split looks back from the bad hours; this looks forward from the bad readings. The
    hours that were bad on both days are the first row of both tables."""
    bad = df[df["now"] >= threshold].copy()
    bad["a_day_later"] = np.where(bad["y"] >= threshold,
                                  f"1 still at {threshold} or more", f"2 back under {threshold}")
    return direction_table(bad, "a_day_later")


def without_average_error(df, by):
    """The same rows with each group's average error taken out. Inside every group of `by`, the ridge's
    forecast and its band are moved by the ridge's mean error in that group, and persistence's forecast by
    persistence's mean error. The readings (`now`, `y`) are not touched.

    This uses the outcomes, so nobody could have made these forecasts. It is a measurement: what is left
    of a group's MAE once a constant offset is gone."""
    out = df.copy()
    ridge_off = (df["point"] - df["y"]).groupby(df[by]).transform("mean")
    same_off = (df["persistence"] - df["y"]).groupby(df[by]).transform("mean")
    for c in ("point", "lower", "upper"):
        out[c] = df[c] - ridge_off
    out["persistence"] = df["persistence"] - same_off
    return out


def show(title, table):
    print(f"\n{title}")
    if table.empty:
        print("(no hours)")
        return
    shown = table.copy()
    for c in ("now", "forecast", "actual", "bias_ridge", "bias_persistence", "mae_ridge", "mae_persistence"):
        shown[c] = shown[c].round(1) + 0.0              # + 0.0 so that a bias of -0.0 prints as 0.0
    for c in ("too_low_ridge", "too_low_persistence"):
        shown[c] = shown[c].round(2)
    shown["inside_band"] = shown["inside_band"].round(3)
    print(shown.to_string(index=False))


def main():
    f = usable(load_features(PRIMARY))
    folds = walk_forward(f.index)
    df = with_levels(out_of_sample(f, folds, feature_columns(f)))
    ridge_mae = (df["point"] - df["y"]).abs().mean()
    same_mae = (df["persistence"] - df["y"]).abs().mean()
    inside = ((df["y"] >= df["lower"]) & (df["y"] <= df["upper"])).mean()
    pd.set_option("display.width", 250)
    print(f"sensor {PRIMARY} · {len(df):,} out-of-sample forecasts · overall MAE ridge {ridge_mae:.2f} "
          f"vs persistence {same_mae:.2f} (must be Step 8's two numbers)")
    print(f"bias ridge {(df['point'] - df['y']).mean():+.2f}, persistence "
          f"{(df['persistence'] - df['y']).mean():+.2f} · {inside:.3f} of the actuals inside the band")

    tables = {
        "1 by the level that came": direction_table(df, "outcome_level"),
        "2 by the level when the forecast was made": direction_table(df, "origin_level"),
        "3 winter window only, by the level when the forecast was made":
            direction_table(df[df["fold"] == WINTER_FOLD], "origin_level"),
        f"4 hours that turned out at {BAD_AIR} or more, by the level a day earlier": bad_air_split(df),
        f"5 forecasts made at {BAD_AIR} or more, by the level a day later": bad_now_split(df),
        "6 by test window": direction_table(df, "window"),
        "7 by test window, each window's average error taken out":
            direction_table(without_average_error(df, "window"), "window"),
    }
    for title, table in tables.items():
        show(title, table)

    Path("results").mkdir(exist_ok=True)
    out = pd.concat([t.assign(table=title) for title, t in tables.items() if len(t)], ignore_index=True)
    out.insert(0, "table", out.pop("table"))
    numbers = [c for c in COLUMNS if c not in ("segment", "n")]
    out[numbers] = out[numbers].astype(float).round(4) + 0.0        # four decimals; -0.0 becomes 0.0
    out.to_csv("results/error_direction.csv", index=False)
    print("\nwritten: results/error_direction.csv")


if __name__ == "__main__":
    main()
