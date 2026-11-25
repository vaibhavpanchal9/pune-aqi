"""Step 9. Prediction intervals: not just "8.56", but "and here is the range".

    python intervals.py           # -> results/intervals.csv

A point forecast of 45 µg/m³ is more useful with an honest band around it: "between 30 and 70, eight
times out of ten". Three ways to get an 80% band (10th to 90th percentile), all judged the same way:

  residual_quantiles   Fit the point model on the early part of the training window, look at its errors on
                       the LAST 8 weeks of training (a calibration set the fit never saw), and take the 10th
                       and 90th percentile of those errors. Band = forecast + those two numbers. Simple,
                       and honest because the errors come from data the fit did not see.
  residual_ratio       The same, but on RELATIVE errors (error / forecast). The band then scales with the
                       forecast: narrow on a clean day, wide on a bad one. Error analysis showed the MAE is
                       6 at Good levels and 25 at Poor levels -- a fixed-width band cannot be right at both.
  quantile_regression  Two linear models trained directly to predict the 10th and the 90th percentile
                       (pinball loss) from the same features. No point model involved.

Judged by two numbers on the six walk-forward folds:
  coverage  share of actual values that fell inside the band. Target 0.80. Above = honest but wide;
            below = overconfident. Both matter.
  width     mean (upper - lower). Narrower is better *only if* coverage holds.
Plus coverage inside the "Poor or worse" hours (actual above 90), because that is where a band earns its
keep. The folds have very different numbers of such hours, and some have none, so in the summary this is
the share over ALL of them and not the mean of the folds (see evaluate_intervals).

The pictures of the band are drawn by readme_figures.py.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from splits import walk_forward
from train import make_ridge

TARGET = "y"
ALPHA = 0.20                   # 80% band: quantiles ALPHA/2 and 1 - ALPHA/2
CAL_WEEKS = 8                  # the tail of the training window used to measure errors
POOR = 90                      # µg/m³: an hour is "Poor or worse" when the actual is above this


def split_calibration(train, weeks=CAL_WEEKS):
    cut = train.index.max() - pd.DateOffset(weeks=weeks)
    return train[train.index <= cut], train[train.index > cut]


def residual_band(train, test, cols, ratio=False, alpha=ALPHA):
    """(point, lower, upper) for test rows from residual quantiles measured on a calibration tail."""
    fit, cal = split_calibration(train)
    point_model = make_ridge(cols)
    cal_pred = point_model(fit, cal.drop(columns=[TARGET]))
    err = cal[TARGET] - cal_pred
    if ratio:
        err = err / cal_pred.clip(lower=1.0)
    lo_q, hi_q = np.quantile(err, alpha / 2), np.quantile(err, 1 - alpha / 2)
    # the final point forecast uses the WHOLE training window, as the product model will
    point = make_ridge(cols)(train, test)
    if ratio:
        base = point.clip(lower=1.0)
        return point, point + lo_q * base, point + hi_q * base
    return point, point + lo_q, point + hi_q


def quantile_regression_band(train, test, cols, alpha=ALPHA):
    """(point, lower, upper) from three linear quantile models: 0.5, alpha/2, 1 - alpha/2."""
    out = {}
    for q in (0.5, alpha / 2, 1 - alpha / 2):
        model = make_pipeline(StandardScaler(), QuantileRegressor(quantile=q, alpha=0.0, solver="highs"))
        model.fit(train[cols], train[TARGET])
        out[q] = pd.Series(model.predict(test[cols]), index=test.index)
    return out[0.5], out[alpha / 2], out[1 - alpha / 2]


METHODS = {
    "residual_quantiles":  lambda tr, te, cols: residual_band(tr, te, cols, ratio=False),
    "residual_ratio":      lambda tr, te, cols: residual_band(tr, te, cols, ratio=True),
    "quantile_regression": quantile_regression_band,
}


def coverage(y, lo, hi):
    inside = (y >= lo) & (y <= hi)
    return float(inside.mean()) if len(y) else float("nan")


def evaluate_intervals(method, features, folds, cols):
    """(table, frame). The table has one row per fold and then one summary row, fold = "mean".

    In the summary row, coverage and width are the mean of the folds, and n and n_poor_plus are totals.
    coverage_poor_plus is the share over all bad-air hours of all folds. It is NOT the mean of the folds:
    one fold can have two hundred such hours and another three, and a plain mean lets the three weigh as
    much as the two hundred. Until 25 Nov 2026 this was that plain mean, printed next to the total, and it
    was read as a share of the total.

    The frame has every test row: y, point, lower, upper, fold."""
    rows, frames = [], []
    for i, (tr_idx, te_idx) in enumerate(folds, start=1):
        train, test = features.loc[tr_idx], features.loc[te_idx]
        point, lo, hi = method(train, test.drop(columns=[TARGET]), cols)
        y = test[TARGET]
        poor = y > POOR
        rows.append({"fold": i, "n": len(y), "coverage": coverage(y, lo, hi),
                     "width": float((hi - lo).mean()),
                     "coverage_poor_plus": coverage(y[poor], lo[poor], hi[poor]) if poor.any() else np.nan,
                     "n_poor_plus": int(poor.sum())})
        frames.append(pd.DataFrame({"y": y, "point": point, "lower": lo, "upper": hi, "fold": i}))
    out, every = pd.DataFrame(rows), pd.concat(frames)
    poor = every["y"] > POOR
    mean = {"fold": "mean", "n": int(out["n"].sum()), "coverage": out["coverage"].mean(),
            "width": out["width"].mean(),
            "coverage_poor_plus": coverage(every["y"][poor], every["lower"][poor], every["upper"][poor]),
            "n_poor_plus": int(out["n_poor_plus"].sum())}
    return pd.concat([out, pd.DataFrame([mean])], ignore_index=True), every


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    folds = walk_forward(f.index)
    cols = feature_columns(f)

    results = []
    for name, method in METHODS.items():
        print(f"evaluating {name} ...", flush=True)
        table, _ = evaluate_intervals(method, f, folds, cols)
        table.insert(0, "method", name)
        results.append(table)

    Path("results").mkdir(exist_ok=True)
    allres = pd.concat(results, ignore_index=True)
    allres.to_csv("results/intervals.csv", index=False)

    pd.set_option("display.width", 160)
    print(f"\nsensor {args.sensor} · nominal coverage {1 - ALPHA:.0%} · {len(folds)} folds\n")
    means = allres[allres["fold"] == "mean"].set_index("method")
    folds_only = allres[allres["fold"] != "mean"]
    print("mean of the folds:")
    print(means[["coverage", "width"]].round(3).to_string())
    print("\nper fold:")
    print(folds_only.pivot(index="fold", columns="method", values="coverage").round(3).to_string())

    # bad-air hours: how many each fold has is printed with the shares, and the last column is all of them
    hours = folds_only[folds_only["method"] == next(iter(METHODS))].set_index("fold")["n_poor_plus"]
    poor = folds_only.pivot(index="method", columns="fold", values="coverage_poor_plus").loc[list(METHODS)]
    poor.columns = [f"fold {k} ({hours[k]} h)" for k in poor.columns]
    poor[f"all ({int(hours.sum())} h)"] = means["coverage_poor_plus"]
    print(f"\nbad-air hours (actual above {POOR}): share inside the band, in each fold and over all of them")
    print(poor.round(3).to_string())

    # pick: closest to nominal coverage; ties broken by width
    fold_miss = folds_only.assign(miss=(folds_only["coverage"] - (1 - ALPHA)).abs()).groupby("method")["miss"].mean()
    means = means.assign(fold_miss=fold_miss)
    honest = means[means["coverage"] >= (1 - ALPHA) - 0.02]        # not systematically overconfident
    best = honest.sort_values(["fold_miss", "width"]).index[0]
    print(f"\nmean coverage and fold-to-fold miss:\n{means[['coverage', 'width', 'fold_miss']].round(3).to_string()}")
    print(f"\npick: {best}  (coverage {means.loc[best, 'coverage']:.3f}, worst fold "
          f"{folds_only[folds_only['method'] == best]['coverage'].min():.3f}, width {means.loc[best, 'width']:.1f})")
    print("written: results/intervals.csv")


if __name__ == "__main__":
    main()
