"""Step 7 (2/2). The evaluation harness: one way to score ANY forecaster on the walk-forward folds.

    python evaluate.py                 # the four baselines, six folds -> results/baselines_folds.csv, figures/folds.png
    python evaluate.py --sensor 12236443

From Python (Step 8 uses exactly this):

    from evaluate import evaluate
    table = evaluate(my_fit_predict, features, folds, name="hgb")

A forecaster is any function  fit_predict(train, test) -> predictions for test  where `train` and
`test` are slices of the feature table and the predictions are a Series aligned to test.index.
It may learn whatever it likes from `train`; it must not look at test["y"]. The harness never passes
the target of a test row to the forecaster -- it only compares afterwards.

The output is one row per fold (n, MAE, RMSE, bias, dates) plus a "mean" row. The number that matters
is the mean MAE across folds, and the spread across folds says how much one season can swing it.
"""

import argparse
from pathlib import Path

import pandas as pd

from baselines import load_features
from dataset import PRIMARY, usable
from metrics import score
from splits import walk_forward, describe

TARGET = "y"


# ----------------------------------------------------------------------------- the harness
def evaluate(fit_predict, features, folds, name="model"):
    """Score one forecaster on every fold. Returns a DataFrame: one row per fold + a 'mean' row."""
    rows = []
    for i, (train_idx, test_idx) in enumerate(folds, start=1):
        train = features.loc[train_idx]
        test = features.loc[test_idx]
        test_blind = test.drop(columns=[TARGET])          # the forecaster never sees test targets
        yhat = pd.Series(fit_predict(train, test_blind), index=test.index, dtype=float)
        s = score(test[TARGET], yhat)
        rows.append({"model": name, "fold": i, **s,
                     "test_from": test.index.min(), "test_to": test.index.max()})
    out = pd.DataFrame(rows)
    mean = {"model": name, "fold": "mean", "n": int(out["n"].sum()),
            "mae": out["mae"].mean(), "rmse": out["rmse"].mean(), "bias": out["bias"].mean(),
            "test_from": out["test_from"].min(), "test_to": out["test_to"].max()}
    return pd.concat([out, pd.DataFrame([mean])], ignore_index=True)


def summary(tables):
    """Several evaluate() outputs -> one table: rows = models, columns = fold MAEs + mean, sorted by mean."""
    allrows = pd.concat(tables, ignore_index=True)
    wide = allrows.pivot(index="model", columns="fold", values="mae")
    cols = [c for c in wide.columns if c != "mean"] + ["mean"]
    return wide[cols].sort_values("mean")


# ----------------------------------------------------------------------------- the baselines as fit_predict
def persistence(train, test):
    return test["value"]


def weekly_naive(train, test):
    return test["lag_144"]


def mean_24h(train, test):
    return test["roll_24"]


def climatology(train, test):
    table = train.groupby(["month_ist", "hour_ist"])[TARGET].mean()
    keys = list(zip(test["month_ist"], test["hour_ist"]))
    return pd.Series(table.reindex(keys).to_numpy(), index=test.index)


BASELINES = {"persistence": persistence, "weekly_naive": weekly_naive,
             "mean_24h": mean_24h, "climatology": climatology}


# ----------------------------------------------------------------------------- the picture of the folds
def plot_folds(folds, path):
    """One horizontal bar per fold: training span, the gap, the test window. Saved to `path`."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = describe(folds)
    fig, ax = plt.subplots(figsize=(10, 0.6 * len(d) + 1.6))
    for _, r in d.iterrows():
        y = r["fold"]
        ax.barh(y, (r["train_to"] - r["train_from"]).days, left=r["train_from"], height=0.5,
                color="#2E6F9E", label="train" if y == 1 else None)
        ax.barh(y, (r["test_to"] - r["test_from"]).days, left=r["test_from"], height=0.5,
                color="#B7791F", label="test" if y == 1 else None)
    ax.set_yticks(d["fold"])
    ax.set_yticklabels([f"fold {k}" for k in d["fold"]])
    ax.invert_yaxis()
    ax.set_title("Walk-forward folds: expanding training window, 24 h gap, 8-week test windows")
    ax.legend(loc="upper right")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    folds = walk_forward(f.index)
    tables = [evaluate(fn, f, folds, name=name) for name, fn in BASELINES.items()]

    Path("results").mkdir(exist_ok=True)
    long = pd.concat(tables, ignore_index=True)
    long.to_csv("results/baselines_folds.csv", index=False)
    plot_folds(folds, "figures/folds.png")

    pd.set_option("display.width", 160)
    print(f"sensor {args.sensor} · {len(folds)} folds · {len(f)} usable rows")
    print("\nMAE per fold (µg/m³):")
    print(summary(tables).round(2).to_string())
    best = summary(tables).index[0]
    best_mean = summary(tables)["mean"].iloc[0]
    print(f"\nBENCHMARK (mean MAE across folds): {best}  {best_mean:.2f} µg/m³")
    print("written: results/baselines_folds.csv, figures/folds.png")


if __name__ == "__main__":
    main()
