"""Tests for the band-sizing experiment (band_calibration.py). Mostly: it cannot see the future.

    pytest tests/test_band_calibration.py -v

A rolling band is re-sized from recent errors, and an error is only known 24 hours after its forecast
was made. If the code used an error too early, the experiment would flatter the rolling band with
information a live system never has. The first two tests pin the timing down to the hour.
"""

import numpy as np
import pandas as pd

import band_calibration as bc
from splits import walk_forward

HOUR = pd.Timedelta(hours=1)


def hourly(n, start="2026-01-01 00:30"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


# ----------------------------------------------------------------------------- what a rolling window may use
def test_an_error_is_used_only_once_its_target_hour_has_passed():
    """The error of origin hour k is the number k, so a window's smallest and largest show what was used."""
    idx = hourly(200)
    errors = pd.Series(np.arange(200.0), index=idx)
    q = bc.rolling_quantiles(errors, idx[[100, 150]], days=2, qs=(0.0, 0.5, 1.0), min_n=1)
    # at hour 100 the newest known error is origin 76 (76 + 24 = 100); two days of them reach back to 29
    assert (q.loc[idx[100], "lo"], q.loc[idx[100], "hi"], q.loc[idx[100], "n"]) == (29.0, 76.0, 48)
    assert (q.loc[idx[150], "lo"], q.loc[idx[150], "hi"], q.loc[idx[150], "n"]) == (79.0, 126.0, 48)


def test_changing_the_future_never_changes_a_band_in_the_past():
    rng = np.random.default_rng(0)
    idx = hourly(400)
    errors = pd.Series(rng.normal(0, 0.2, 400), index=idx)
    before = bc.rolling_quantiles(errors, idx, days=7, min_n=24)
    wild = errors.copy()
    wild.iloc[300:] = 99.0                                       # from origin hour 300 on, every forecast is far off
    after = bc.rolling_quantiles(wild, idx, days=7, min_n=24)
    not_yet_known = idx < idx[300] + 24 * HOUR                   # origin 300's error is known at hour 324
    pd.testing.assert_frame_equal(before[not_yet_known], after[not_yet_known])
    assert after.loc[idx[324], "hi"] > before.loc[idx[324], "hi"]             # from then on the band does learn


def test_a_window_with_too_few_known_errors_gives_no_numbers():
    idx = hourly(100)
    errors = pd.Series(0.1, index=idx)
    q = bc.rolling_quantiles(errors, idx[[30, 99]], days=7, min_n=48)
    assert q.loc[idx[30], ["lo", "mid", "hi"]].isna().all() and q.loc[idx[30], "n"] == 7      # origins 0 .. 6
    assert q.loc[idx[99], ["lo", "mid", "hi"]].notna().all() and q.loc[idx[99], "n"] == 76    # origins 0 .. 75


# ----------------------------------------------------------------------------- the bands of one fold
def test_with_too_few_known_errors_the_rolling_band_falls_back_to_the_live_one():
    rng = np.random.default_rng(2)
    before = hourly(24 * 56)                                     # eight calibration weeks ...
    test = hourly(48, start="2026-03-10 00:30")                  # ... then a 12-day hole, then two test days
    static_errors = {8: pd.Series(rng.normal(0, 0.1, len(before)), index=before)}
    point = pd.Series(50.0, index=test)
    test_errors = pd.Series(rng.normal(0, 0.1, len(test)), index=test)
    bands, fell_back = bc.bands_for_fold(point, static_errors, test_errors,
                                         schemes=[("static", 8), ("rolling", 7), ("rolling", 56)])
    assert fell_back == {"static_8w": 0.0, "rolling_7d": 1.0, "rolling_56d": 0.0}
    for static, rolling in zip(bands["static_8w"], bands["rolling_7d"]):        # lower, middle, upper
        pd.testing.assert_series_equal(static, rolling)
    assert not bands["rolling_56d"][0].equals(bands["static_8w"][0])            # this one had errors to use


def test_when_errors_grow_a_rolling_band_widens_and_a_static_one_does_not():
    rng = np.random.default_rng(1)
    before = hourly(24 * 56)
    test = hourly(24 * 56, start=str(before[-1] + 25 * HOUR))
    calm = pd.Series(rng.normal(0, 0.10, len(before)), index=before)            # errors of about 10% ...
    point = pd.Series(50.0, index=test)
    y = point * (1 + rng.normal(0, 0.30, len(test)))                            # ... then of about 30%
    bands, _ = bc.bands_for_fold(point, {8: calm}, bc.relative_error(y, point), schemes=[("static", 8), ("rolling", 7)])
    cover = {name: bc.coverage(y, lo, hi) for name, (lo, _, hi) in bands.items()}
    assert cover["static_8w"] < 0.45                             # sized for calm weeks: far too narrow
    assert 0.70 < cover["rolling_7d"] < 0.85                     # about a week late, then close to 0.80


def test_the_band_is_a_share_of_the_forecast_and_tiny_forecasts_count_as_one():
    point = pd.Series([50.0, 0.5])
    lo, mid, hi = bc.band_from(point, (-0.2, 0.1, 0.4))
    assert list(lo) == [40.0, 0.3] and list(mid) == [55.0, 0.6] and list(hi) == [70.0, 0.9]
    assert list(bc.relative_error(pd.Series([60.0, 3.0]), point)) == [0.2, 2.5]


# ----------------------------------------------------------------------------- scoring
def test_interval_score_is_width_plus_a_fine_for_every_miss():
    y = pd.Series([10.0, 10.0, 10.0])
    lo = pd.Series([8.0, 12.0, 5.0])
    hi = pd.Series([12.0, 15.0, 9.0])
    # inside: width 4.  below by 2: width 3 + 10 * 2.  above by 1: width 4 + 10 * 1.
    assert bc.interval_score(y, lo, hi) == (4 + 23 + 14) / 3


def test_fold_miss_sees_what_the_mean_hides():
    per_fold = pd.DataFrame({"scheme": ["a", "a", "b", "b"], "fold": [1, 2, 1, 2],
                             "coverage": [0.95, 0.65, 0.81, 0.79], "width": 20.0, "interval_score": 30.0,
                             "below": 0.1, "above": 0.1, "mae_middle": 5.0, "mae_ridge": 5.0,
                             "mae_persistence": 6.0, "fallback_share": 0.0})
    s = bc.summarise(per_fold)
    assert list(s["coverage"].round(3)) == [0.8, 0.8]            # the same mean coverage ...
    assert list(s["fold_miss"].round(3)) == [0.15, 0.01]         # ... and very different honesty
    assert (s.loc["a", "worst_fold"], s.loc["a", "best_fold"]) == (0.65, 0.95)


def summary(*rows):
    return pd.DataFrame(rows, columns=["scheme", "coverage", "fold_miss", "width", "interval_score"]).set_index("scheme")


def test_the_rule_keeps_the_live_band_unless_another_is_clearly_better():
    live = ("static_8w", 0.80, 0.100, 30.0, 40.0)                # scheme, coverage, fold_miss, width, interval score
    # clearly better: 0.05 closer to 0.80 fold by fold, and a lower interval score
    assert bc.pick(summary(live, ("rolling_14d", 0.79, 0.050, 28.0, 36.0)))[0] == "rolling_14d"
    # closer, but by less than the 0.02 the rule asks for
    assert bc.pick(summary(live, ("rolling_14d", 0.79, 0.085, 28.0, 36.0)))[0] == "static_8w"
    # closer fold by fold only by being so wide that the interval score is worse
    assert bc.pick(summary(live, ("rolling_14d", 0.84, 0.050, 45.0, 44.0)))[0] == "static_8w"
    # the closest of all fails on interval score; one that passes both rules is taken instead
    assert bc.pick(summary(live, ("rolling_28d", 0.79, 0.060, 29.0, 38.0),
                           ("rolling_3d", 0.76, 0.030, 24.0, 43.0)))[0] == "rolling_28d"
    # two within 0.01 of each other: the one listed first (the longer memory) wins
    assert bc.pick(summary(live, ("rolling_14d", 0.79, 0.030, 28.0, 36.0),
                           ("rolling_7d", 0.79, 0.021, 27.0, 35.0)))[0] == "rolling_14d"
    # nothing else to choose from
    assert bc.pick(summary(live))[0] == "static_8w"
    for _, reason in (bc.pick(summary(live)), bc.pick(summary(live, ("rolling_14d", 0.79, 0.085, 28.0, 36.0)))):
        assert isinstance(reason, str) and reason                # a decision always comes with its reason


# ----------------------------------------------------------------------------- the whole experiment, small
def test_static_8w_here_is_exactly_the_band_of_intervals_py():
    """The experiment's baseline must be the band that is live, to the last digit, or it compares to nothing."""
    rng = np.random.default_rng(3)
    idx = hourly(24 * 7 * 44)                                    # 44 weeks of hours
    hours = np.arange(len(idx))
    value = pd.Series(40 + 10 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 4, len(idx)), index=idx)
    f = pd.DataFrame({"value": value, "lag_1": value.shift(1), "lag_24": value.shift(24),
                      "hour_sin": np.sin(2 * np.pi * hours / 24), "y": value.shift(-24)}).dropna()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=150)
    cols = ["value", "lag_1", "lag_24", "hour_sin"]
    per_fold, largest_difference = bc.evaluate_schemes(f, folds, cols, schemes=[("static", 8), ("rolling", 14)])
    assert largest_difference == 0.0
    assert list(per_fold["scheme"]) == ["static_8w", "rolling_14d"] * 2 and list(per_fold["fold"]) == [1, 1, 2, 2]
    assert per_fold["coverage"].between(0.6, 0.95).all()         # an 80% band on well-behaved data
    assert (per_fold["mae_ridge"] < per_fold["mae_persistence"]).all()
    assert (per_fold["fallback_share"] == 0).all()
