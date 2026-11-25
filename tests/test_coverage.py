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


# ----------------------------------------------------------------------------- the bad-air hours
def by_hand(*folds_spec):
    """Hand-made folds for evaluate_intervals. Each fold is a list of (actual, inside the band?) pairs.
    Returns (features, folds, method): the band of the method is value - 1 to value + 1, and value is the
    actual for an hour that is to be inside and 500 below it for an hour that is to be outside."""
    rows = [{"y": float(y), "value": float(y) if inside else float(y) - 500.0}
            for spec in folds_spec for y, inside in spec]
    idx = pd.date_range("2026-01-01 00:30", periods=len(rows) + 1, freq="h", tz="UTC")
    f = pd.DataFrame([{"y": 0.0, "value": 0.0}] + rows, index=idx)          # row 0 is the training row
    folds, first = [], 1
    for spec in folds_spec:
        folds.append((idx[:1], idx[first:first + len(spec)]))
        first += len(spec)

    def method(train, test, cols):
        return test["value"], test["value"] - 1, test["value"] + 1
    return f, folds, method


def test_the_summary_for_bad_air_hours_is_the_share_of_all_of_them_not_the_mean_of_the_folds():
    f, folds, method = by_hand(
        [(100, True)] * 8 + [(100, False)] * 2 + [(50, True)] * 2,          # 10 bad-air hours, 8 inside
        [(100, False)] * 2 + [(90, False), (50, True)])                     # 2 bad-air hours, none inside
    table, _ = evaluate_intervals(method, f, folds, ["value"])
    assert list(table["n_poor_plus"]) == [10, 2, 12]                        # 90 itself is not "above 90"
    assert list(table["coverage_poor_plus"].iloc[:2]) == [0.8, 0.0]         # the folds, each on its own
    summary = table[table["fold"] == "mean"].iloc[0]
    assert summary["coverage_poor_plus"] == 8 / 12                          # not (0.8 + 0.0) / 2
    assert summary["coverage"] == (10 / 12 + 1 / 4) / 2                     # coverage itself stays the mean of the folds
    assert summary["n"] == 16


def test_a_fold_without_bad_air_hours_has_no_share_and_does_not_enter_the_summary():
    f, folds, method = by_hand([(100, True), (100, False), (100, False), (40, True)],
                               [(40, True), (60, False)])
    table, _ = evaluate_intervals(method, f, folds, ["value"])
    assert list(table["n_poor_plus"]) == [3, 0, 3]
    assert table["coverage_poor_plus"].iloc[0] == 1 / 3 and np.isnan(table["coverage_poor_plus"].iloc[1])
    assert table["coverage_poor_plus"].iloc[2] == 1 / 3


def test_with_no_bad_air_at_all_the_summary_is_empty_too():
    f, folds, method = by_hand([(40, True), (60, False)], [(30, True)])
    table, _ = evaluate_intervals(method, f, folds, ["value"])
    assert list(table["n_poor_plus"]) == [0, 0, 0] and table["coverage_poor_plus"].isna().all()
