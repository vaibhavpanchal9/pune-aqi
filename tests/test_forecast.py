"""Step 10 tests: the JSON model IS the evaluated model, and the hourly job only issues real forecasts.

    pytest tests/test_forecast.py -v

No database: the readings are built by hand and pushed through the real feature code.
"""

import json

import numpy as np
import pandas as pd

from dataset import feature_columns
from fit_model import build_spec, fit_pipeline, walk_forward_numbers
from forecast import predict, feature_rows, issuable, forecast_table, COLUMNS
from intervals import residual_band
from tests.test_train import synthetic_features


def split(f, weeks=4):
    cut = f.index.max() - pd.Timedelta(weeks=weeks)
    return f[f.index <= cut - pd.Timedelta(hours=24)], f[f.index > cut]


# ---------------------------------------------------------------- the saved numbers are the model
def test_json_model_reproduces_sklearn():
    f = synthetic_features()
    cols = feature_columns(f)
    spec, model = build_spec(f, cols)
    point, _, _ = predict(spec, f, clip=False)
    assert np.allclose(point.to_numpy(), model.predict(f[cols]), atol=1e-8)
    assert len(spec["mean"]) == len(spec["scale"]) == len(spec["coef"]) == len(cols)


def test_product_band_equals_the_evaluated_band():
    """forecast.predict with a spec from fit_model == intervals.residual_band(ratio=True): same point,
    same lower, same upper, on rows neither has seen. The product serves exactly what Step 9 measured."""
    f = synthetic_features()
    cols = feature_columns(f)
    train, test = split(f)
    ev_point, ev_lo, ev_hi = residual_band(train, test.drop(columns=["y"]), cols, ratio=True)
    spec, _ = build_spec(train, cols)
    pr_point, pr_lo, pr_hi = predict(spec, test, clip=False)
    for a, b in [(ev_point, pr_point), (ev_lo, pr_lo), (ev_hi, pr_hi)]:
        assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-8)


def test_spec_survives_json_round_trip():
    f = synthetic_features()
    cols = feature_columns(f)
    spec, _ = build_spec(f, cols)
    again = json.loads(json.dumps(spec))
    a, _, _ = predict(spec, f.iloc[:100])
    b, _, _ = predict(again, f.iloc[:100])
    assert (a.to_numpy() == b.to_numpy()).all()


def test_point_and_band_are_clipped_at_zero_and_ordered():
    full = synthetic_features()
    spec, _ = build_spec(full, feature_columns(full))
    spec["intercept"] -= 1000.0                          # force negative raw predictions
    f = full.iloc[:200]
    point, lo, hi = predict(spec, f)
    assert (point >= 0).all() and (lo >= 0).all() and (hi >= 0).all()
    assert (lo <= point).all() and (point <= hi).all()
    raw_point, raw_lo, _ = predict(spec, f, clip=False)
    assert (raw_point < 0).all() and (raw_lo < 0).all()  # the clip did something


# ---------------------------------------------------------------- which hours get a forecast
def readings_until(now, hours=24 * 20, hole=()):
    """`hours` hourly readings, the newest about 3 h before `now` (the usual upstream lag), timestamps at
    xx:30 like OpenAQ's. `hole` = positions to delete, to simulate an outage."""
    end = now.floor("h") - pd.Timedelta(hours=3) + pd.Timedelta(minutes=30)
    idx = pd.date_range(end=end, periods=hours, freq="h")
    s = pd.Series(40 + 10 * np.sin(np.arange(hours) / 24 * 2 * np.pi), index=idx)
    return s.drop(idx[list(hole)]) if hole else s


def test_only_recent_complete_future_origins_are_issued():
    now = pd.Timestamp("2026-11-09 06:10", tz="UTC")
    # a 5-hour hole (12:30-16:30 the day before): longer than the gap policy fills, so it stays missing
    s = readings_until(now, hole=range(24 * 20 - 16, 24 * 20 - 11))
    f = feature_rows(s)
    rows, counts = issuable(f, now, horizon=24)
    assert counts["in_window"] == 22                      # 06:30 yesterday .. 03:30 today, the newest reading
    assert rows.index.min() > now - pd.Timedelta(hours=24)
    assert (rows.index + pd.Timedelta(hours=24) > now).all()
    assert not rows[feature_columns(f)].isna().any().any()
    # the hours right after the hole have a missing lag_1 / lag_2 ...: fewer complete rows than in the window
    assert counts["complete"] < counts["in_window"]
    assert counts["future_target"] == counts["complete"]  # every origin in the last 24 h targets the future


def test_nothing_is_issued_when_the_data_is_too_old():
    now = pd.Timestamp("2026-11-09 06:10", tz="UTC")
    s = readings_until(now - pd.Timedelta(hours=30))       # newest reading 33 h old
    rows, counts = issuable(feature_rows(s), now, horizon=24)
    assert rows.empty and counts["in_window"] == 0


def test_forecast_table_has_the_table_shape():
    now = pd.Timestamp("2026-11-09 06:10", tz="UTC")
    f_train = synthetic_features()
    spec, _ = build_spec(f_train, feature_columns(f_train), version="vtest", sensor_id=42)
    table, counts = forecast_table(spec, feature_rows(readings_until(now)), now)
    assert list(table.columns) == COLUMNS
    assert len(table) == counts["future_target"] > 0
    assert (table["target_time"] - table["origin_time"] == pd.Timedelta(hours=24)).all()
    assert (table["sensor_id"] == 42).all() and (table["model_version"] == "vtest").all()
    assert (table["lower"] <= table["point"]).all() and (table["point"] <= table["upper"]).all()


# ---------------------------------------------------------------- provenance
def test_walk_forward_numbers_come_from_the_file(tmp_path):
    p = tmp_path / "model_comparison.csv"
    pd.DataFrame({"model": ["ridge", "ridge", "persistence", "persistence"],
                  "fold": ["1", "mean", "1", "mean"],
                  "mae": [8.0, 8.66, 9.0, 9.36]}).to_csv(p, index=False)
    wf = walk_forward_numbers(str(p))
    assert wf["ridge_mae"] == 8.66 and wf["persistence_mae"] == 9.36 and wf["folds"] == 1
    assert walk_forward_numbers(str(tmp_path / "missing.csv")) is None


def test_fit_pipeline_is_the_step8_ridge():
    """Same numbers as train.make_ridge on the same rows."""
    from train import make_ridge
    f = synthetic_features()
    cols = feature_columns(f)
    train, test = split(f)
    a = make_ridge(cols)(train, test.drop(columns=["y"]))
    b = fit_pipeline(train, cols).predict(test[cols])
    assert np.allclose(a.to_numpy(), b, atol=1e-8)
