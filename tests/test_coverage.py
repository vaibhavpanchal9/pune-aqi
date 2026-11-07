"""Intervals: bands contain the point, coverage is measured honestly, and a wide band covers everything."""

import numpy as np
import pandas as pd

from dataset import feature_columns
from intervals import residual_band, coverage, evaluate_intervals, METHODS
from splits import walk_forward
from tests.test_train import synthetic_features


def test_coverage_arithmetic():
    y = pd.Series([1.0, 2.0, 3.0, 4.0])
    lo = pd.Series([0.0, 2.5, 2.0, 0.0])
    hi = pd.Series([2.0, 3.0, 4.0, 3.0])
    assert coverage(y, lo, hi) == 0.5           # rows 1 and 3 inside


def test_band_contains_the_point_and_is_ordered():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=1, test_weeks=4, min_train_days=90)
    tr, te = folds[0]
    cols = feature_columns(f)
    for ratio in (False, True):
        point, lo, hi = residual_band(f.loc[tr], f.loc[te].drop(columns=["y"]), cols, ratio=ratio)
        assert (lo <= point).all() and (point <= hi).all()


def test_coverage_is_near_nominal_on_well_behaved_data():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=90)
    table, _ = evaluate_intervals(METHODS["residual_quantiles"], f, folds, feature_columns(f))
    mean_cov = table[table["fold"] == "mean"]["coverage"].iloc[0]
    assert 0.65 <= mean_cov <= 0.95


def test_an_infinitely_wide_band_covers_everything():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=1, test_weeks=4, min_train_days=90)

    def silly(train, test, cols):
        p = test["value"]
        return p, p - 1e9, p + 1e9
    table, _ = evaluate_intervals(silly, f, folds, feature_columns(f))
    assert table["coverage"].iloc[0] == 1.0
    assert np.isclose(table["width"].iloc[0], 2e9)
