"""Tests for readme_figures.py: the pictures must not flatter the data.

    pytest tests/test_readme_figures.py -v

Three ways a forecast picture can mislead, each pinned down here: drawing a forecast at the hour it was
made instead of the hour it is for, drawing a line across a hole in the data, and picking the window by eye.
"""

import numpy as np
import pandas as pd

import readme_figures as rf

HOUR, DAY = pd.Timedelta(hours=1), pd.Timedelta(days=1)
START = pd.Timestamp("2026-03-01 00:00", tz="Asia/Kolkata")


def rows(index, y=50.0, point=50.0):
    return pd.DataFrame({"fold": 1, "y": y, "point": point, "lower": 40.0, "upper": 60.0, "persistence": 55.0},
                        index=index)


def test_a_forecast_is_drawn_at_the_hour_it_is_for():
    made_at = pd.DatetimeIndex([pd.Timestamp("2026-01-01 00:30", tz="UTC")])
    out = rf.at_target_time(rows(made_at))
    assert out.index[0] == pd.Timestamp("2026-01-02 00:30", tz="UTC")            # 24 hours later
    assert str(out.index.tz) == "Asia/Kolkata" and out.index[0].hour == 6        # shown in IST


def test_the_window_is_the_most_recent_one_that_is_full_enough():
    full = pd.date_range(START + HOUR, START + 28 * DAY, freq="h")               # four weeks, every hour
    last_five_days = full > START + 23 * DAY
    index = full[~last_five_days | (np.arange(len(full)) % 2 == 0)]              # the last 5 days: every second hour
    start, end, share = rf.recent_dense_window(index, [(START, START + 28 * DAY)], days=14, min_share=0.90)
    # ending on the last day would hold only 82% of its hours; three days earlier it is 93%
    assert end == START + 25 * DAY and start == end - 14 * DAY
    assert round(share, 3) == round((12 * 24 + 2 * 12) / 336, 3)


def test_if_no_window_is_full_enough_the_fullest_is_returned_with_its_true_share():
    every_second_hour = pd.date_range(START + HOUR, START + 28 * DAY, freq="2h")
    start, end, share = rf.recent_dense_window(every_second_hour, [(START, START + 28 * DAY)], days=14, min_share=0.90)
    assert share == 0.5 and end == START + 28 * DAY                              # all equal: the most recent one


def test_a_window_never_straddles_two_test_windows():
    older = (START, START + 20 * DAY)
    newer = (START + 20 * DAY, START + 30 * DAY)                                 # too short to hold 14 days
    index = pd.date_range(START + HOUR, START + 30 * DAY, freq="h")
    start, end, share = rf.recent_dense_window(index, [older, newer], days=14, min_share=0.90)
    assert (start, end, share) == (START + 6 * DAY, START + 20 * DAY, 1.0)       # inside the older one


def test_a_missing_hour_becomes_an_empty_row_so_the_line_breaks():
    index = pd.DatetimeIndex([START + HOUR, START + 2 * HOUR, START + 5 * HOUR, START + 6 * HOUR])
    g = rf.on_hourly_grid(rows(index), START, START + 6 * HOUR)
    assert len(g) == 6 and list(g["y"].isna()) == [False, False, True, True, False, False]
    assert g.index[0] == START + HOUR and g.index[-1] == START + 6 * HOUR        # start excluded, end included


def test_the_numbers_under_a_picture_are_the_numbers_on_it():
    index = pd.date_range(START + HOUR, periods=4, freq="h")
    frame = rows(index, y=[50.0, 70.0, 45.0, 290.0], point=[50.0, 50.0, 50.0, 60.0])
    frame["upper"] = [60.0, 60.0, 60.0, 85.0]
    d = rf.describe_window(rf.on_hourly_grid(frame, START, START + 6 * HOUR))    # two more hours with nothing
    assert (d["hours"], d["scored"]) == (6, 4)
    assert d["inside"] == 0.5                                                    # 50 and 45 are inside 40..60
    assert d["mae"] == (0 + 20 + 5 + 230) / 4
    assert (d["peak_actual"], d["peak_forecast"], d["peak_upper"]) == (290.0, 60.0, 85.0)
    assert d["peak_time"] == START + 4 * HOUR
