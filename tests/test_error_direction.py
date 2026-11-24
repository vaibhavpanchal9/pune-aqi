"""Tests for error_direction.py: bias has a sign, and the hours are sorted by the right thing.

    pytest tests/test_error_direction.py -v
"""

import pandas as pd

import error_direction as ed


def forecasts(rows):
    """rows: (reading when the forecast was made, ridge forecast, actual a day later)"""
    return pd.DataFrame(rows, columns=["persistence", "point", "y"]).assign(fold=1)


def test_bias_is_forecast_minus_actual_so_negative_means_too_low():
    df = forecasts([(100, 80, 120), (100, 90, 110), (100, 130, 120)]).assign(group="all")
    t = ed.direction_table(df, "group").iloc[0]
    assert t["n"] == 3 and (t["now"], t["forecast"], t["actual"]) == (100.0, 100.0, 350 / 3)
    assert t["bias_ridge"] == (-40 - 20 + 10) / 3                       # two forecasts 40 and 20 low, one 10 high
    assert t["too_low_ridge"] == 2 / 3 and t["mae_ridge"] == 70 / 3
    assert t["bias_persistence"] == (-20 - 10 - 20) / 3                 # "same as now" said 100 every time
    assert t["too_low_persistence"] == 1.0 and t["mae_persistence"] == 50 / 3


def test_an_hour_gets_two_labels_the_level_that_came_and_the_level_at_the_time():
    df = ed.with_levels(forecasts([(20, 25, 95), (95, 70, 40), (90, 80, 30)]))
    assert list(df["origin_level"]) == ["1 Good (<=30)", "4 Poor or worse (>90)", "4 Poor or worse (>90)"]
    assert list(df["outcome_level"]) == ["4 Poor or worse (>90)", "2 Satisfactory (31-60)", "2 Satisfactory (31-60)"]


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


def test_a_table_with_no_hours_still_has_its_columns():
    t = ed.bad_air_split(forecasts([(20, 25, 30), (40, 35, 50)]), threshold=90)
    assert len(t) == 0 and list(t.columns) == ed.COLUMNS
