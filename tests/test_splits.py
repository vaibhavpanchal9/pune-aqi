"""Step 7 tests: the three properties a time-series split must have, plus the two ways it can go wrong.

    pytest tests/test_splits.py -v
"""

import numpy as np
import pandas as pd
import pytest

from splits import walk_forward, describe


def hourly_index(n_hours, start="2025-02-18 19:30", drop_every=None):
    idx = pd.date_range(start, periods=n_hours, freq="h", tz="UTC")
    if drop_every:                                # punch holes, like real data
        idx = idx[np.arange(n_hours) % drop_every != 0]
    return idx


def test_train_is_strictly_before_test_with_the_gap():
    folds = walk_forward(hourly_index(24 * 400), n_folds=5, test_weeks=4, gap_hours=24, min_train_days=90)
    for train, test in folds:
        assert train.max() <= test.min() - pd.Timedelta("24h")
        assert len(train.intersection(test)) == 0


def test_folds_are_consecutive_and_do_not_overlap():
    folds = walk_forward(hourly_index(24 * 400), n_folds=5, test_weeks=4, min_train_days=90)
    tests = [te for _, te in folds]
    for earlier, later in zip(tests, tests[1:]):
        assert earlier.max() < later.min()                      # chronological, no overlap
        assert later.min() - earlier.max() == pd.Timedelta("1h")   # and no hole between windows
    assert all(len(te) == 24 * 7 * 4 for te in tests)           # four weeks of hours each


def test_training_window_expands():
    folds = walk_forward(hourly_index(24 * 400), n_folds=5, test_weeks=4, min_train_days=90)
    sizes = [len(tr) for tr, _ in folds]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
    assert all(tr.min() == folds[0][0].min() for tr, _ in folds)   # always from the very start


def test_missing_hours_do_not_shift_the_windows():
    full = walk_forward(hourly_index(24 * 700))                       # defaults: 6 folds x 8 weeks
    holed = walk_forward(hourly_index(24 * 700, drop_every=7))
    for (tr1, te1), (tr2, te2) in zip(full, holed):
        assert te1.min() <= te2.min() and te2.max() <= te1.max()   # same window in TIME ...
        assert len(te2) < len(te1)                                  # ... fewer rows in it


def test_too_little_history_is_refused():
    with pytest.raises(ValueError):
        walk_forward(hourly_index(24 * 120), n_folds=5, test_weeks=4, min_train_days=90)


def test_defaults_cover_48_weeks_in_six_folds():
    d = describe(walk_forward(hourly_index(24 * 700)))
    assert list(d["fold"]) == [1, 2, 3, 4, 5, 6]
    assert (d["test_rows"] == 24 * 7 * 8).all()
    assert d["test_to"].iloc[-1] - d["test_from"].iloc[0] >= pd.Timedelta("48W") - pd.Timedelta("1h")
    assert (d["gap_hours"] >= 24).all()
