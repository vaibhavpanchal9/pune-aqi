"""Step 8. Models through the same harness as the baselines.

    python train.py                          # three models + four baselines on six folds -> results/model_comparison.csv
    python train.py --sensor 12236443
    python train.py --models ridge hgb_all   # a subset

A model here is a fit_predict(train, test) function, exactly like a baseline (evaluate.py), so it is
scored on the same rows by the same code. Three are defined:

  ridge            a linear model on every feature, after standardising them. The floor: if gradient
                   boosting cannot beat a straight line through the lags, the features are the problem.
  ridge_lags_only  the same line without the time-of-day / season features -- do they help at all?
  hgb_lags_only    gradient boosting on the recent past only (value, lags, rolling means, counts).
  hgb_all          gradient boosting on everything: the lags plus hour / weekday / month and their
                   sine-cosine encodings.
  hgb_all_delta    boosting predicting the CHANGE over 24 h (see formulations below); _sq = squared loss.
  hgb_all_logratio boosting predicting the change as a ratio.
  blend_ridge_hgb  the average of ridge and hgb_all_delta: a line that extrapolates plus trees that
                   bend -- their mistakes are different, so the average is often better than either.

Each model can predict the target in one of three forms ("formulation"):

  level     y itself. Natural, but trees cannot extrapolate: asked about a December at 100 µg/m³ after
            training on a February-to-November at 15-60, they answer "about 60" and are badly wrong.
  delta     y - value, the CHANGE over the next 24 hours; the prediction is value + change. Persistence
            carries the level, the model learns only the correction -- a quantity it has seen in every season.
  logratio  log(y / value), the change as a ratio; the prediction is value * exp(ratio). A 20% rise in
            December and a 20% rise in June look the same to it.

Gradient boosting = many small decision trees, each one fitted to the mistakes of the ones before it.
HistGradientBoostingRegressor is scikit-learn's fast version (it bins each feature into 255 buckets
first). It is trained with absolute-error loss because the number we report is MAE, and because
absolute error is less bothered by the occasional 300 µg/m³ hour than squared error is.

Determinism: random_state is fixed and early stopping is off, so two runs give identical numbers.
Run it twice and diff the CSVs; if they differ, something is wrong.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from evaluate import evaluate, summary, BASELINES
from splits import walk_forward

TARGET = "y"
SEED = 0


def lag_columns(f):
    """The 'recent past' features only: the current value, the lags, the rolling means and their counts."""
    return [c for c in feature_columns(f) if c == "value" or c.startswith(("lag_", "roll_", "n_"))]


def encode(train, formulation):
    """The training target in the chosen formulation."""
    if formulation == "level":
        return train[TARGET]
    if formulation == "delta":
        return train[TARGET] - train["value"]
    if formulation == "logratio":
        return np.log(train[TARGET] / train["value"])
    raise ValueError(formulation)


def decode(test, raw, formulation):
    """Back from the model's output to a forecast of y."""
    if formulation == "level":
        return raw
    if formulation == "delta":
        return test["value"] + raw
    if formulation == "logratio":
        return test["value"] * np.exp(raw)
    raise ValueError(formulation)


def make_ridge(cols, formulation="level", alpha=1.0):
    def fit_predict(train, test):
        model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        model.fit(train[cols], encode(train, formulation))
        raw = pd.Series(model.predict(test[cols]), index=test.index)
        return decode(test, raw, formulation)
    return fit_predict


def make_hgb(cols, formulation="level", **params):
    settings = dict(loss="absolute_error", max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                    min_samples_leaf=20, early_stopping=False, random_state=SEED)
    settings.update(params)

    def fit_predict(train, test):
        model = HistGradientBoostingRegressor(**settings)
        model.fit(train[cols], encode(train, formulation))
        raw = pd.Series(model.predict(test[cols]), index=test.index)
        return decode(test, raw, formulation)
    return fit_predict


def make_blend(fns, weights=None):
    """Average the forecasts of several models. Different mistakes cancel; shared mistakes don't."""
    weights = weights or [1.0 / len(fns)] * len(fns)

    def fit_predict(train, test):
        preds = [fn(train, test) for fn in fns]
        return sum(w * p for w, p in zip(weights, preds))
    return fit_predict


def models_for(f):
    allc, lagc = feature_columns(f), lag_columns(f)
    ridge = make_ridge(allc)
    hgb_delta = make_hgb(allc, "delta")
    return {
        "ridge":             ridge,
        "ridge_lags_only":   make_ridge(lagc),
        "hgb_lags_only":     make_hgb(lagc),
        "hgb_all":           make_hgb(allc),
        "hgb_all_delta":     hgb_delta,
        "hgb_all_delta_sq":  make_hgb(allc, "delta", loss="squared_error"),
        "hgb_all_logratio":  make_hgb(allc, "logratio"),
        "blend_ridge_hgb":   make_blend([ridge, hgb_delta]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--models", nargs="*", default=None, help="subset of model names to run")
    ap.add_argument("--out", default="results/model_comparison.csv")
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    folds = walk_forward(f.index)
    models = models_for(f)
    if args.models:
        models = {k: models[k] for k in args.models}

    tables = []
    for name, fn in BASELINES.items():
        tables.append(evaluate(fn, f, folds, name=name))
    for name, fn in models.items():
        print(f"fitting {name} on {len(folds)} folds ...", flush=True)
        tables.append(evaluate(fn, f, folds, name=name))

    Path(args.out).parent.mkdir(exist_ok=True)
    pd.concat(tables, ignore_index=True).to_csv(args.out, index=False)

    pd.set_option("display.width", 160)
    wide = summary(tables).round(2)
    print(f"\nsensor {args.sensor} · {len(f)} usable rows · features: {len(feature_columns(f))} "
          f"(lags-only: {len(lag_columns(f))})")
    print("\nMAE per fold (µg/m³), best first:")
    print(wide.to_string())
    bench = wide.loc["persistence", "mean"]
    best = wide.index[0]
    print(f"\nbenchmark (persistence) {bench:.2f} · best {best} {wide.loc[best, 'mean']:.2f} · "
          f"improvement {100 * (bench - wide.loc[best, 'mean']) / bench:.1f}%")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
