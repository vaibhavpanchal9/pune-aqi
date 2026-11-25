"""Tests for error_direction.py: bias has a sign, and the hours are sorted by the right thing.

    pytest tests/test_error_direction.py -v
"""

import pandas as pd
import pytest

import error_direction as ed


def forecasts(rows, fold=1):
    """rows: (reading when the forecast was made, ridge forecast, actual a day later).
    The band is a share of the forecast, as it is live: here from 0.75 x forecast to 1.40 x forecast."""
    df = pd.DataFrame(rows, columns=["persistence", "point", "y"]).assign(fold=fold)
    df["now"] = df["persistence"]
    df["lower"], df["upper"] = df["point"] * 0.75, df["point"] * 1.40
    return df


def test_bias_is_forecast_minus_actual_so_negative_means_too_low():
    df = forecasts([(100, 80, 120), (100, 90, 110), (100, 130, 120)]).assign(group="all")
    t = ed.direction_table(df, "group").iloc[0]
    assert t["n"] == 3 and (t["now"], t["forecast"], t["actual"]) == (100.0, 100.0, 350 / 3)
    assert t["bias_ridge"] == (-40 - 20 + 10) / 3                       # two forecasts 40 and 20 low, one 10 high
    assert t["too_low_ridge"] == 2 / 3 and t["mae_ridge"] == 70 / 3
    assert t["bias_persistence"] == (-20 - 10 - 20) / 3                 # "same as now" said 100 every time
    assert t["too_low_persistence"] == 1.0 and t["mae_persistence"] == 50 / 3
    assert t["inside_band"] == 2 / 3                                    # 120 is above 80's band (60 to 112)


def test_an_actual_on_the_edge_of_the_band_is_inside():
    df = forecasts([(100, 100, 60), (100, 100, 140), (100, 100, 140.5), (100, 100, 59.5)]).assign(group="all")
    df["lower"], df["upper"] = 60.0, 140.0
    assert ed.direction_table(df, "group").iloc[0]["inside_band"] == 0.5


def test_an_hour_gets_two_labels_the_level_that_came_and_the_level_at_the_time():
    df = ed.with_levels(forecasts([(20, 25, 95), (95, 70, 40), (90, 80, 30)]))
    assert list(df["origin_level"]) == ["1 Good (<=30)", "4 Poor or worse (>90)", "4 Poor or worse (>90)"]
    assert list(df["outcome_level"]) == ["4 Poor or worse (>90)", "2 Satisfactory (31-60)", "2 Satisfactory (31-60)"]
    assert list(df["now"]) == [20, 95, 90] and set(df["window"]) == {"window 1 (winter)"}
    assert set(ed.with_levels(forecasts([(20, 25, 95)], fold=3))["window"]) == {"window 3"}


def test_bad_air_hours_are_split_by_whether_the_air_was_already_bad():
    df = forecasts([(120, 100, 130),      # a bad spell going on: the ridge pulls back, "same as now" is closer
                    (110, 95, 100),
                    (40, 45, 150),        # a bad spell arriving: neither saw it
                    (60, 50, 60)])        # never bad: not in this table at all
    t = ed.bad_air_split(df, threshold=90).set_index("segment")
    assert list(t.index) == ["1 already at 90 or more", "2 still under 90"] and list(t["n"]) == [2, 1]
    going_on, arriving = t.loc["1 already at 90 or more"], t.loc["2 still under 90"]
    assert (going_on["mae_ridge"], going_on["mae_persistence"]) == (17.5, 10.0)       # (30 + 5) / 2, (10 + 10) / 2
    assert (arriving["mae_ridge"], arriving["mae_persistence"]) == (105.0, 110.0)
    assert going_on["bias_ridge"] == -17.5 and going_on["too_low_ridge"] == 1.0


def test_forecasts_made_in_bad_air_are_split_by_what_came():
    df = forecasts([(120, 100, 130),      # still bad a day later: the pull-back was wrong
                    (110, 95, 100),
                    (95, 85, 60),         # the air cleared: the pull-back was right, "same as now" far off
                    (40, 45, 150)])       # not bad when the forecast was made: not in this table at all
    t = ed.bad_now_split(df, threshold=90).set_index("segment")
    assert list(t.index) == ["1 still at 90 or more", "2 back under 90"] and list(t["n"]) == [2, 1]
    stayed, cleared = t.loc["1 still at 90 or more"], t.loc["2 back under 90"]
    assert (stayed["mae_ridge"], stayed["mae_persistence"]) == (17.5, 10.0)
    assert (cleared["mae_ridge"], cleared["mae_persistence"]) == (25.0, 35.0)
    assert cleared["bias_ridge"] == 25.0 and cleared["too_low_ridge"] == 0.0


def test_the_hours_bad_on_both_days_are_the_first_row_of_both_splits():
    df = forecasts([(120, 100, 130), (110, 95, 100), (95, 85, 60), (40, 45, 150), (60, 50, 60)])
    looking_back, looking_forward = ed.bad_air_split(df).iloc[0], ed.bad_now_split(df).iloc[0]
    assert looking_back["n"] == 2
    assert looking_back.drop("segment").tolist() == looking_forward.drop("segment").tolist()


def test_taking_the_average_error_out_removes_the_offset_and_nothing_else():
    df = pd.concat([forecasts([(80, 90, 100), (90, 94, 100)]).assign(window="A"),      # the ridge runs 8 low
                    forecasts([(50, 51, 50), (50, 49, 50)]).assign(window="B")],        # no offset at all
                   ignore_index=True)
    moved = ed.without_average_error(df, "window")
    before = ed.direction_table(df, "window").set_index("segment")
    after = ed.direction_table(moved, "window").set_index("segment")
    assert (before.loc["A", "bias_ridge"], before.loc["A", "mae_ridge"]) == (-8.0, 8.0)
    assert after.loc["A", "bias_ridge"] == pytest.approx(0) and after.loc["A", "mae_ridge"] == pytest.approx(2)
    assert after.loc["A", "bias_persistence"] == pytest.approx(0)                       # errors -20 and -10 ...
    assert after.loc["A", "mae_persistence"] == pytest.approx(5)                        # ... become -5 and +5
    assert after.loc["B", "mae_ridge"] == pytest.approx(1)                              # nothing to take out
    assert list(after["now"]) == [85.0, 50.0] and list(after["actual"]) == [100.0, 50.0]
    assert (moved["upper"] - moved["lower"]).tolist() == pytest.approx((df["upper"] - df["lower"]).tolist())
    assert (moved["point"] - moved["lower"]).tolist() == pytest.approx((df["point"] - df["lower"]).tolist())
    assert list(df["point"]) == [90, 94, 51, 49]                                        # the input is not changed


def test_a_table_with_no_hours_still_has_its_columns():
    t = ed.bad_air_split(forecasts([(20, 25, 30), (40, 35, 50)]), threshold=90)
    assert len(t) == 0 and list(t.columns) == ed.COLUMNS
