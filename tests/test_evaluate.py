"""The harness: one row per fold plus a mean, the forecaster never sees test targets, numbers add up."""

import numpy as np
import pandas as pd
import pytest

from evaluate import evaluate, summary, persistence
from splits import walk_forward


def fake_features(n_hours=24 * 500, seed=0):
    """A feature table whose target is exactly lag_1 + 1, so a forecaster can be perfect on purpose."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01 00:30", periods=n_hours, freq="h", tz="UTC")
    value = pd.Series(rng.normal(40, 10, n_hours), index=idx)
    f = pd.DataFrame({"value": value, "lag_1": value.shift(1), "lag_144": value.shift(144),
                      "roll_24": value.rolling(24, min_periods=1).mean(),
                      "month_ist": idx.month, "hour_ist": idx.hour})
    f["y"] = f["lag_1"] + 1.0
    return f.dropna()


def test_one_row_per_fold_plus_mean():
    f = fake_features()
    folds = walk_forward(f.index, n_folds=4, test_weeks=4, min_train_days=90)
    t = evaluate(persistence, f, folds, name="p")
    assert len(t) == 5
    assert list(t["fold"]) == [1, 2, 3, 4, "mean"]
    assert t["mae"].iloc[-1] == pytest.approx(t["mae"].iloc[:-1].mean())
    assert t["n"].iloc[-1] == t["n"].iloc[:-1].sum()


def test_a_forecaster_that_knows_the_rule_scores_zero():
    f = fake_features()
    folds = walk_forward(f.index, n_folds=3, test_weeks=4, min_train_days=90)
    t = evaluate(lambda train, test: test["lag_1"] + 1.0, f, folds, name="oracle")
    assert (t["mae"] == 0).all()


def test_forecaster_never_receives_the_test_target():
    f = fake_features()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=90)

    def nosy(train, test):
        assert "y" not in test.columns          # the harness must have removed it
        assert "y" in train.columns             # but training targets are available
        return test["value"]
    evaluate(nosy, f, folds, name="nosy")


def test_constant_forecast_mae_matches_hand_calculation():
    f = fake_features()
    folds = walk_forward(f.index, n_folds=1, test_weeks=4, min_train_days=90)
    t = evaluate(lambda train, test: pd.Series(40.0, index=test.index), f, folds, name="const")
    _, test_idx = folds[0]
    expected = float((f.loc[test_idx, "y"] - 40.0).abs().mean())
    assert t["mae"].iloc[0] == pytest.approx(expected)


def test_summary_sorts_models_by_mean_mae():
    f = fake_features()
    folds = walk_forward(f.index, n_folds=3, test_weeks=4, min_train_days=90)
    good = evaluate(lambda tr, te: te["lag_1"] + 1.0, f, folds, name="good")
    bad = evaluate(lambda tr, te: pd.Series(0.0, index=te.index), f, folds, name="bad")
    s = summary([bad, good])
    assert list(s.index) == ["good", "bad"]
    assert list(s.columns) == [1, 2, 3, "mean"]
