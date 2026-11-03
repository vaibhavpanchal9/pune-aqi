"""The models run through the harness, learn a learnable rule, and are deterministic."""

import numpy as np
import pandas as pd

from dataset import to_grid, make_features, usable
from evaluate import evaluate, persistence
from splits import walk_forward
from train import models_for, make_hgb, lag_columns


def synthetic_features(n_hours=24 * 420, seed=0):
    """A series with a daily cycle plus noise, pushed through the real feature code."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-02-18 19:30", periods=n_hours, freq="h", tz="UTC")
    t = np.arange(n_hours)
    v = 40 + 12 * np.sin(2 * np.pi * t / 24) + 6 * np.sin(2 * np.pi * t / (24 * 7)) + rng.normal(0, 3, n_hours)
    s = pd.Series(np.clip(v, 1, None), index=idx)
    grid = to_grid(s)
    return usable(make_features(grid, grid))


def test_models_return_one_prediction_per_test_row():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=90)
    for name, fn in models_for(f).items():
        t = evaluate(fn, f, folds, name=name)
        assert list(t["fold"]) == [1, 2, "mean"]
        assert (t["n"].iloc[:-1] == [len(te) for _, te in folds]).all()


def test_gradient_boosting_beats_persistence_on_a_learnable_series():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=90)
    base = evaluate(persistence, f, folds, name="persistence")["mae"].iloc[-1]
    hgb = evaluate(make_hgb(lag_columns(f)), f, folds, name="hgb")["mae"].iloc[-1]
    assert hgb < base


def test_training_is_deterministic():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=1, test_weeks=4, min_train_days=90)
    fn = models_for(f)["hgb_all"]
    a = evaluate(fn, f, folds, name="a")["mae"].iloc[0]
    b = evaluate(fn, f, folds, name="b")["mae"].iloc[0]
    assert a == b


def test_lag_columns_exclude_time_features():
    f = synthetic_features()
    cols = lag_columns(f)
    assert "hour_ist" not in cols and "hour_sin" not in cols and "y" not in cols
    assert "lag_24" in cols and "roll_24" in cols and "value" in cols


def test_delta_and_logratio_round_trip():
    from train import encode, decode
    f = synthetic_features().iloc[:50]
    for form in ("level", "delta", "logratio"):
        raw = encode(f, form)
        back = decode(f, raw, form)
        assert np.allclose(back, f["y"])
