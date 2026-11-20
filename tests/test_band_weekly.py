"""Tests for band_weekly.py: which hours go into which week, and how the weeks are counted.

    pytest tests/test_band_weekly.py -v
"""

import numpy as np
import pandas as pd

import band_weekly as bw
from intervals import METHODS, evaluate_intervals
from splits import walk_forward

HOUR, DAY = pd.Timedelta(hours=1), pd.Timedelta(days=1)
START = pd.Timestamp("2026-01-01 00:30", tz="UTC")


def scored(index, inside, fold=1):
    """Hand-made scored hours: forecast 50, band 40 to 60, persistence 55. An actual is 50 (inside) or 70."""
    y = np.where(np.asarray(inside, dtype=bool), 50.0, 70.0)
    return pd.DataFrame({"fold": fold, "y": y, "point": 50.0, "lower": 40.0, "upper": 60.0, "persistence": 55.0},
                        index=index)


# ----------------------------------------------------------------------------- the windows
def test_the_windows_here_are_the_windows_of_walk_forward():
    idx = pd.date_range(START, periods=24 * 7 * 80, freq="h")              # 80 weeks: 48 to test, 32 before them
    folds = walk_forward(idx)
    windows = bw.fold_windows(idx.max())
    assert len(windows) == len(folds) == 6 and windows[-1][1] == idx.max()
    for (_, test), (start, end) in zip(folds, windows):
        assert test.min() == start + HOUR and test.max() == end            # a row t is in if start < t <= end
        assert end - start == pd.Timedelta(weeks=8)
    assert all(first[1] == second[0] for first, second in zip(windows, windows[1:]))    # back to back


# ----------------------------------------------------------------------------- cutting a window into blocks
def test_a_window_is_cut_into_weeks_and_each_week_is_scored_alone():
    idx = pd.date_range(START + HOUR, START + 14 * DAY, freq="h")          # two full weeks
    inside = np.r_[np.ones(168, dtype=bool), np.tile([True, False], 84)]   # week 1: all in. week 2: every second hour
    b = bw.blocks(scored(idx, inside), [(START, START + 14 * DAY)], days=7)
    assert list(b["block"]) == [1, 2] and list(b["scored"]) == [168, 168] and b["counted"].all()
    assert list(b["coverage"]) == [1.0, 0.5]
    assert list(b["mae_ridge"]) == [0.0, 10.0]                             # actuals 50, then 50 and 70 in turn
    assert list(b["mae_persistence"]) == [5.0, 10.0]
    assert list(b["bias"]) == [0.0, -10.0] and list(b["mean_actual"]) == [50.0, 60.0]

    both = bw.blocks(scored(idx, inside), [(START, START + 14 * DAY)], days=14)
    assert len(both) == 1 and both.loc[0, "coverage"] == 0.75              # one fortnight: (168 + 84) / 336


def test_an_hour_on_the_boundary_belongs_to_the_week_that_ends_there():
    idx = pd.DatetimeIndex([START + 7 * DAY, START + 7 * DAY + HOUR])
    b = bw.blocks(scored(idx, [True, False]), [(START, START + 14 * DAY)], days=7, min_share=0)
    assert list(b["scored"]) == [1, 1] and list(b["coverage"]) == [1.0, 0.0]


def test_a_thin_week_is_listed_but_not_counted():
    full_week = pd.date_range(START + HOUR, START + 7 * DAY, freq="h")
    fifty_hours = pd.date_range(START + 7 * DAY + HOUR, periods=50, freq="h")
    idx = full_week.append(fifty_hours)
    b = bw.blocks(scored(idx, np.ones(len(idx))), [(START, START + 21 * DAY)], days=7)
    assert list(b["scored"]) == [168, 50, 0]                               # week 3 has no scored hour at all
    assert list(b["counted"]) == [True, False, False]                      # under half of 168 hours: left out
    s = bw.spread(b)
    assert (s["blocks"], s["left_out"]) == (1, 2)


def test_days_left_over_at_the_end_of_a_window_make_no_block():
    idx = pd.date_range(START + HOUR, START + 17 * DAY, freq="h")
    b = bw.blocks(scored(idx, np.ones(len(idx))), [(START, START + 17 * DAY)], days=7)
    assert list(b["block"]) == [1, 2] and b["scored"].sum() == 336         # the last 3 days are in no block


def test_each_fold_has_its_own_blocks():
    one = pd.date_range(START + HOUR, START + 7 * DAY, freq="h")
    two = pd.date_range(START + 7 * DAY + HOUR, START + 14 * DAY, freq="h")
    oos = pd.concat([scored(one, np.ones(168), fold=1), scored(two, np.zeros(168), fold=2)])
    b = bw.blocks(oos, [(START, START + 7 * DAY), (START + 7 * DAY, START + 14 * DAY)], days=7)
    assert list(zip(b["fold"], b["block"], b["coverage"])) == [(1, 1, 1.0), (2, 1, 0.0)]


# ----------------------------------------------------------------------------- the yardstick
def test_the_yardstick_counts_the_weeks_under_each_line():
    b = pd.DataFrame({"counted": [True] * 5 + [False],
                      "coverage": [0.45, 0.62, 0.71, 0.80, 0.90, 0.10],    # the last one is not counted
                      "mae_ridge": [5.0] * 6,
                      "mae_persistence": [6.0, 4.0, 6.0, 6.0, 5.0, 9.0]})
    s = bw.spread(b)
    assert (s["blocks"], s["left_out"]) == (5, 1)
    assert (s["lowest"], s["median"], s["highest"]) == (0.45, 0.71, 0.90)
    assert [s[f"under_{t:.2f}"] for t in bw.THRESHOLDS] == [1, 1, 2, 2, 3, 3]     # 0.80 is not under 0.80
    assert s["ridge_better"] == 3                                          # an equal MAE is not "better"


def test_the_grid_shows_a_week_that_is_not_counted_as_empty():
    b = pd.DataFrame({"fold": [1, 1, 2, 2], "block": [1, 2, 1, 2], "counted": [True, False, True, True],
                      "coverage": [0.9, 0.2, 0.7, 0.8]})
    g = bw.grid(b, "coverage")
    assert g.loc[1, 1] == 0.9 and np.isnan(g.loc[1, 2]) and list(g.loc[2]) == [0.7, 0.8]


# ----------------------------------------------------------------------------- with a real model, small
def test_every_test_row_is_scored_with_the_live_recipe_and_lands_in_one_week():
    rng = np.random.default_rng(3)
    idx = pd.date_range(START, periods=24 * 7 * 44, freq="h")              # 44 weeks of hours
    hours = np.arange(len(idx))
    value = pd.Series(40 + 10 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 4, len(idx)), index=idx)
    f = pd.DataFrame({"value": value, "lag_1": value.shift(1), "lag_24": value.shift(24),
                      "hour_sin": np.sin(2 * np.pi * hours / 24), "y": value.shift(-24)}).dropna()
    cols = ["value", "lag_1", "lag_24", "hour_sin"]
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=150)

    oos = bw.out_of_sample(f, folds, cols)
    assert len(oos) == sum(len(test) for _, test in folds) and set(oos["fold"]) == {1, 2}

    inside = (oos["y"] >= oos["lower"]) & (oos["y"] <= oos["upper"])
    step9, _ = evaluate_intervals(METHODS["residual_ratio"], f, folds, cols)          # the Step 9 harness
    assert list(inside.groupby(oos["fold"]).mean()) == list(step9["coverage"].iloc[:2])

    weeks = bw.blocks(oos, bw.fold_windows(f.index.max(), n_folds=2, test_weeks=4), days=7)
    assert len(weeks) == 8 and weeks["scored"].sum() == len(oos) and weeks["counted"].all()
