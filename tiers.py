"""Step 10b. Fallback tiers: the same ridge on shorter lag sets, for the hours the full model cannot do.

    python tiers.py              # -> results/tier_comparison.csv, results/tier_availability.csv

The problem, measured on 10 Nov (docs/decisions.md): the full model needs the reading 1, 2, 3, 6, 12,
24, 48, 144 and 168 hours ago. After a hole longer than the gap policy fills (3 h) each of those lags
is missing in turn, so for 24 hours after an outage -- and again 2, 6 and 7 days later -- there is no
complete row and no forecast.

The fix is NOT to invent the missing lags: the model never trained on invented values. It is to keep
smaller models that do not ask for them:

    full    every feature                              needs 168 h of unbroken history
    day     without the 48 / 144 / 168 h lags          needs 24 h
    short   without any lag beyond 3 h                 needs 3 h

Each is the same recipe -- standardise, Ridge(alpha=1) -- trained on every row it can use (a shorter
lag set has more usable rows) and tested on the SAME six eight-week windows as Step 8. The hourly job
uses the richest tier whose features are all present for that hour: "the cascade".

A fallback is only worth having if it is honest about being worse, so each tier is scored three ways,
all on out-of-sample forecasts pooled over the six folds:

    common   on the rows the FULL model can also do          -> what do the dropped lags cost?
    served   on the rows it would actually serve              -> the hours after gaps, which may be harder
             (no richer tier is complete there)
    and persistence on those same served rows                 -> the alternative to having a fallback

plus the band: coverage of each tier's own 80% residual-ratio band, overall and on its served rows.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from evaluate import evaluate, predictions
from forecast import assign_tiers
from intervals import METHODS, evaluate_intervals
from metrics import mae
from splits import walk_forward
from train import make_ridge

TARGET = "y"

# name, the features it does WITHOUT, hours of unbroken history it needs. Richest first.
TIERS = [
    ("full",  (),                                                              168),
    ("day",   ("lag_48", "lag_144", "lag_168"),                                 24),
    ("short", ("lag_6", "lag_12", "lag_24", "lag_48", "lag_144", "lag_168"),     3),
]


def tier_defs(all_cols):
    """[{name, features, needs_hours}, ...] richest first, from the full feature list."""
    return [{"name": name, "features": [c for c in all_cols if c not in without], "needs_hours": needs}
            for name, without, needs in TIERS]


def rows_for(f, cols):
    """The rows a model on `cols` can train and be scored on: its features and the target present."""
    return f.dropna(subset=list(cols) + [TARGET])


def evaluate_tiers(f):
    """Out-of-sample results for every tier and for the cascade. Returns (comparison, availability, oos).

    comparison    one row per tier + one for the cascade + one for 'full only' (what v1 does)
    availability  share of grid hours in the test span that can be forecast, tier by tier
    oos           per test hour: y, the origin value, which tier serves it, each tier's forecast
    """
    all_cols = feature_columns(f)
    tiers = tier_defs(all_cols)
    end = usable(f).index.max()                        # anchor every tier's windows on the full model's

    oos = pd.DataFrame({"y": f[TARGET], "value": f["value"], "served": assign_tiers(f, tiers)})
    per_tier = {}
    for t in tiers:
        rows = rows_for(f, t["features"])
        folds = walk_forward(rows.index, end=end)
        model = make_ridge(t["features"])
        oos[f"pred_{t['name']}"] = predictions(model, rows, folds)
        by_fold = evaluate(model, rows, folds, name=t["name"])
        bands, frame = evaluate_intervals(METHODS["residual_ratio"], rows, folds, t["features"])
        frame = frame.join(oos["served"])
        mine = frame[frame["served"] == t["name"]]
        per_tier[t["name"]] = {
            "usable_rows": len(rows),
            "mae_folds": float(by_fold.loc[by_fold["fold"] == "mean", "mae"].iloc[0]),
            "coverage": float(bands.loc[bands["fold"] == "mean", "coverage"].iloc[0]),
            "worst_fold_coverage": float(bands.loc[bands["fold"] != "mean", "coverage"].min()),
            "width": float(bands.loc[bands["fold"] == "mean", "width"].iloc[0]),
            "coverage_served": float(((mine["y"] >= mine["lower"]) & (mine["y"] <= mine["upper"])).mean())
                               if len(mine) else np.nan,
        }
    pred_cols = [f"pred_{t['name']}" for t in tiers]
    oos = oos.dropna(subset=pred_cols, how="all")      # keep hours at least one tier forecast out of sample

    rows_out = []
    for t in tiers:
        p = oos[f"pred_{t['name']}"]
        common = p.notna() & oos["pred_full"].notna()
        served = p.notna() & (oos["served"] == t["name"])
        rows_out.append({
            "tier": t["name"], "features": len(t["features"]), "needs_hours": t["needs_hours"],
            "usable_rows": per_tier[t["name"]]["usable_rows"],
            "mae_folds": per_tier[t["name"]]["mae_folds"],
            "n_common": int(common.sum()), "mae_common": mae(oos.loc[common, "y"], p[common]),
            "n_served": int(served.sum()),
            "mae_served": mae(oos.loc[served, "y"], p[served]) if served.any() else np.nan,
            "persistence_served": mae(oos.loc[served, "y"], oos.loc[served, "value"]) if served.any() else np.nan,
            "coverage": per_tier[t["name"]]["coverage"],
            "worst_fold_coverage": per_tier[t["name"]]["worst_fold_coverage"],
            "coverage_served": per_tier[t["name"]]["coverage_served"],
            "width": per_tier[t["name"]]["width"],
        })

    # the cascade: for each hour, the forecast of the tier that serves it
    cascade = pd.Series(np.nan, index=oos.index)
    for t in tiers:
        take = (oos["served"] == t["name"]) & oos[f"pred_{t['name']}"].notna()
        cascade[take] = oos.loc[take, f"pred_{t['name']}"]
    has = cascade.notna()
    full = oos["pred_full"].notna()
    for name, mask, pred in [("cascade (v2)", has, cascade), ("full only (v1)", full, oos["pred_full"])]:
        rows_out.append({"tier": name, "n_served": int(mask.sum()),
                         "mae_served": mae(oos.loc[mask, "y"], pred[mask]),
                         "persistence_served": mae(oos.loc[mask, "y"], oos.loc[mask, "value"])})
    comparison = pd.DataFrame(rows_out)

    # availability: of the grid hours in the 48 test weeks, how many can be forecast at all?
    span = f[(f.index > end - pd.DateOffset(weeks=48)) & (f.index <= end)]
    chosen = assign_tiers(span, tiers)
    with_reading = span["value"].notna()
    avail, running = [], pd.Series(False, index=span.index)
    for t in tiers:
        running = running | (chosen == t["name"])
        avail.append({"up_to_tier": t["name"], "hours": int(running.sum()),
                      "share_of_grid_hours": float(running.mean()),
                      "share_of_hours_with_a_reading": float(running[with_reading].mean())})
    availability = pd.DataFrame(avail)
    availability.attrs["grid_hours"] = int(len(span))
    availability.attrs["hours_with_a_reading"] = int(with_reading.sum())
    return comparison, availability, oos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    f = load_features(args.sensor)
    print("evaluating three tiers on six walk-forward folds ...", flush=True)
    comparison, availability, _ = evaluate_tiers(f)

    Path("results").mkdir(exist_ok=True)
    comparison.to_csv("results/tier_comparison.csv", index=False)
    availability.to_csv("results/tier_availability.csv", index=False)

    pd.set_option("display.width", 200)
    tiers = comparison[comparison["tier"].isin([n for n, _, _ in TIERS])].astype(
        {"features": int, "needs_hours": int, "usable_rows": int, "n_common": int})
    print(f"\nsensor {args.sensor} · out-of-sample, six folds of 8 weeks · MAE in µg/m³\n")
    print("what the dropped lags cost (same rows as the full model), and the band:")
    print(tiers[["tier", "features", "needs_hours", "usable_rows", "mae_folds", "n_common", "mae_common",
                 "coverage", "worst_fold_coverage", "width"]].round(3).to_string(index=False))
    print("\nthe rows each tier would actually serve (no richer tier complete), against persistence:")
    print(comparison[["tier", "n_served", "mae_served", "persistence_served", "coverage_served"]]
          .round(3).to_string(index=False))
    print(f"\navailability over the 48 test weeks ({availability.attrs['grid_hours']} grid hours, "
          f"{availability.attrs['hours_with_a_reading']} with a reading):")
    print(availability.round(3).to_string(index=False))
    print("\nwritten: results/tier_comparison.csv, results/tier_availability.csv")


if __name__ == "__main__":
    main()
