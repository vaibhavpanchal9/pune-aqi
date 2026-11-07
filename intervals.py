"""Step 9. Prediction intervals: not just "8.56", but "and here is the range".

    python intervals.py           # -> results/intervals.csv, figures/intervals.png

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
Plus coverage inside the "Poor or worse" hours, because that is where a band earns its keep.
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
    rows, frames = [], []
    for i, (tr_idx, te_idx) in enumerate(folds, start=1):
        train, test = features.loc[tr_idx], features.loc[te_idx]
        point, lo, hi = method(train, test.drop(columns=[TARGET]), cols)
        y = test[TARGET]
        poor = y > 90
        rows.append({"fold": i, "n": len(y), "coverage": coverage(y, lo, hi),
                     "width": float((hi - lo).mean()),
                     "coverage_poor_plus": coverage(y[poor], lo[poor], hi[poor]) if poor.any() else np.nan,
                     "n_poor_plus": int(poor.sum())})
        frames.append(pd.DataFrame({"y": y, "point": point, "lower": lo, "upper": hi, "fold": i}))
    out = pd.DataFrame(rows)
    mean = {"fold": "mean", "n": int(out["n"].sum()), "coverage": out["coverage"].mean(),
            "width": out["width"].mean(), "coverage_poor_plus": out["coverage_poor_plus"].mean(),
            "n_poor_plus": int(out["n_poor_plus"].sum())}
    return pd.concat([out, pd.DataFrame([mean])], ignore_index=True), pd.concat(frames)


def plot_band(frame, path, days=14):
    """The last `days` days of out-of-sample forecasts for one method: band, point, actual."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    f = frame.sort_index().iloc[-24 * days:]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(f.index, f["lower"], f["upper"], color="#2E6F9E", alpha=0.2, label="80% band")
    ax.plot(f.index, f["point"], color="#2E6F9E", lw=1.2, label="forecast (24 h ahead)")
    ax.plot(f.index, f["y"], color="#172029", lw=1.0, label="actual")
    ax.set_ylabel("PM2.5, µg/m³"); ax.set_title(f"Out-of-sample forecasts with an 80% band, last {days} days of fold 6")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    fig.autofmt_xdate(); fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=130); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    folds = walk_forward(f.index)
    cols = feature_columns(f)

    results, frames = [], {}
    for name, method in METHODS.items():
        print(f"evaluating {name} ...", flush=True)
        table, frame = evaluate_intervals(method, f, folds, cols)
        table.insert(0, "method", name)
        results.append(table)
        frames[name] = frame

    Path("results").mkdir(exist_ok=True)
    allres = pd.concat(results, ignore_index=True)
    allres.to_csv("results/intervals.csv", index=False)

    pd.set_option("display.width", 160)
    print(f"\nsensor {args.sensor} · nominal coverage {1 - ALPHA:.0%} · {len(folds)} folds\n")
    means = allres[allres["fold"] == "mean"].set_index("method")
    print(means[["coverage", "width", "coverage_poor_plus", "n_poor_plus"]].round(3).to_string())
    print("\nper fold:")
    print(allres[allres["fold"] != "mean"].pivot(index="fold", columns="method", values="coverage").round(3).to_string())

    # pick: closest to nominal coverage; ties broken by width
    folds_only = allres[allres["fold"] != "mean"]
    fold_miss = folds_only.assign(miss=(folds_only["coverage"] - (1 - ALPHA)).abs()).groupby("method")["miss"].mean()
    means = means.assign(fold_miss=fold_miss)
    honest = means[means["coverage"] >= (1 - ALPHA) - 0.02]        # not systematically overconfident
    best = honest.sort_values(["fold_miss", "width"]).index[0]
    print(f"\nmean coverage and fold-to-fold miss:\n{means[['coverage', 'width', 'fold_miss']].round(3).to_string()}")
    print(f"\npick: {best}  (coverage {means.loc[best, 'coverage']:.3f}, worst fold "
          f"{folds_only[folds_only['method'] == best]['coverage'].min():.3f}, width {means.loc[best, 'width']:.1f})")
    plot_band(frames[best], "figures/intervals.png")
    print("written: results/intervals.csv, figures/intervals.png")


if __name__ == "__main__":
    main()
