"""The metrics on numbers you can check by hand."""

import numpy as np
import pytest

from metrics import mae, rmse, bias, score


def test_perfect_forecast_scores_zero():
    y = [10.0, 20.0, 30.0]
    assert mae(y, y) == 0.0 and rmse(y, y) == 0.0 and bias(y, y) == 0.0


def test_mae_rmse_bias_by_hand():
    y = [10.0, 20.0, 30.0, 40.0]
    yhat = [12.0, 18.0, 30.0, 44.0]        # errors +2, -2, 0, +4
    assert mae(y, yhat) == pytest.approx(2.0)               # (2+2+0+4)/4
    assert rmse(y, yhat) == pytest.approx(np.sqrt(6.0))      # (4+4+0+16)/4 = 6
    assert bias(y, yhat) == pytest.approx(1.0)               # (2-2+0+4)/4


def test_rmse_is_never_below_mae():
    rng = np.random.default_rng(1)
    y = rng.normal(40, 15, 500)
    yhat = y + rng.normal(0, 8, 500)
    assert rmse(y, yhat) >= mae(y, yhat)


def test_missing_values_are_ignored_and_counted():
    y = [10.0, np.nan, 30.0, 40.0]
    yhat = [12.0, 18.0, np.nan, 44.0]
    s = score(y, yhat)
    assert s["n"] == 2
    assert s["mae"] == pytest.approx(3.0)                    # errors +2 and +4


def test_shape_mismatch_is_an_error():
    with pytest.raises(ValueError):
        mae([1.0, 2.0], [1.0])
