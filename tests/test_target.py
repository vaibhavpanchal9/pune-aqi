"""Step 6 tests: the target is 24 hours ahead, features never look forward, the policies do what
decisions.md says. No database needed -- every test builds a tiny series by hand.

    pytest tests/test_target.py -v
"""

import numpy as np
import pandas as pd

from dataset import clean_values, to_grid, fill_short_gaps, make_features, usable


def hourly(values, start="2026-01-01 00:30", drop=()):
    """A UTC hourly Series from a list; `drop` removes hours by position to simulate gaps."""
    idx = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    s = pd.Series(values, index=idx, dtype=float)
    keep = [i for i in range(len(s)) if i not in set(drop)]
    return s.iloc[keep]


# ---------------------------------------------------------------- target alignment
def test_target_is_exactly_24_hours_ahead():
    s = hourly(np.arange(100.0))            # value == hours since start, so the maths is visible
    grid = to_grid(s)
    f = make_features(grid, grid)
    # at hour 10 the target must be the value at hour 34
    assert f["y"].iloc[10] == 34.0
    assert f["lag_24"].iloc[34] == 10.0
    # the last 24 rows have no target: the future does not exist yet
    assert f["y"].iloc[-24:].isna().all()
    assert f["y"].iloc[:-24].notna().all()


def test_features_never_use_the_future():
    s = hourly(np.arange(200.0))
    grid = to_grid(s)
    f = make_features(grid, grid)
    t = 150
    # every feature at row t is computable from rows <= t: perturb the future and nothing changes
    grid2 = grid.copy()
    grid2.iloc[t + 1:] = 9999.0
    f2 = make_features(grid2, grid2)
    cols = [c for c in f.columns if c != "y"]
    pd.testing.assert_frame_equal(f[cols].iloc[:t + 1], f2[cols].iloc[:t + 1])


# ---------------------------------------------------------------- gap policy
def test_gap_of_three_is_filled_gap_of_four_is_not():
    # hours 0..29; remove 10,11,12 (a 3-hour gap) and 20,21,22,23 (a 4-hour gap)
    s = hourly(np.arange(30.0), drop=(10, 11, 12, 20, 21, 22, 23))
    grid = to_grid(s)
    assert len(grid) == 30 and grid.isna().sum() == 7
    filled, was_filled = fill_short_gaps(grid, max_gap=3)
    assert filled.iloc[10:13].tolist() == [9.0, 9.0, 9.0]      # carried forward from hour 9
    assert filled.iloc[20:24].isna().all()                      # left alone
    assert int(was_filled.sum()) == 3


def test_target_is_never_filled():
    s = hourly(np.arange(60.0), drop=(30, 31))
    grid = to_grid(s)
    filled, _ = fill_short_gaps(grid)
    f = make_features(filled, grid)              # target from the UNFILLED grid
    assert filled.iloc[30] == 29.0               # the feature side was filled ...
    assert np.isnan(f["y"].iloc[6])              # ... but hour 6's target (hour 30) stays missing
    assert np.isnan(f["y"].iloc[7])


# ---------------------------------------------------------------- value policy
def test_value_policy_removes_what_decisions_say():
    vals = [20.0, 21.0, -5.0, 0.0, 22.0, 990.0, 23.0,
            7.0, 7.0, 7.0, 7.0, 7.0, 7.0,            # a 6-long flat run
            24.0, 200.0, 25.0,                        # a 4x spike
            26.0, 3.0, 27.0]                          # a 4x dropout
    s = hourly(vals)
    clean, counts = clean_values(s)
    assert counts["negative"] == 1 and counts["zero"] == 1 and counts["ceiling_985plus"] == 1
    assert counts["flat_run_6plus"] == 6
    # 990 is caught twice: by the ceiling rule and as a 4x spike. Rules overlap; rows are removed once.
    assert counts["spike_4x"] == 2 and counts["dropout_4x"] == 1
    assert counts["removed_total"] == 11
    assert np.isnan(clean.iloc[2]) and np.isnan(clean.iloc[3]) and np.isnan(clean.iloc[5])
    assert clean.iloc[7:13].isna().all()
    assert np.isnan(clean.iloc[14]) and np.isnan(clean.iloc[17])
    assert clean.iloc[0] == 20.0 and clean.iloc[18] == 27.0     # good readings untouched, never edited
    assert len(clean) == len(s)                                 # removed means NaN, not dropped


def test_usable_rows_need_every_feature_and_the_target():
    s = hourly(np.arange(300.0))
    grid = to_grid(s)
    f = make_features(grid, grid)
    u = usable(f)
    # lag_168 needs 168 hours of history, y needs 24 hours of future: 300 - 168 - 24 = 108
    assert len(u) == 108
