"""Step 10b tests: the fallback tiers and the cascade that chooses between them.

    pytest tests/test_tiers.py -v

No database. Readings are built by hand, holes are punched in them, and the real feature code,
the real tier definitions and the real hourly-job functions are run on the result.
"""

import json

import numpy as np
import pandas as pd

from dataset import feature_columns, to_grid, fill_short_gaps, make_features
import pytest

from fit_model import build_spec, build_tiered_spec, check_not_overwriting
from forecast import assign_tiers, feature_rows, forecast_table, predict
from modelfile import tiers_of
from tiers import TIERS, tier_defs, evaluate_tiers


def hourly(n_hours, holes=(), seed=0, start="2025-02-18 19:30"):
    """A noisy daily cycle, one reading per hour, with the given positions deleted (outages)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n_hours, freq="h", tz="UTC")
    t = np.arange(n_hours)
    v = 40 + 12 * np.sin(2 * np.pi * t / 24) + 6 * np.sin(2 * np.pi * t / (24 * 7)) + rng.normal(0, 3, n_hours)
    s = pd.Series(np.clip(v, 1, None), index=idx)
    return s.drop(idx[list(holes)]) if len(holes) else s


def features_with_target(series):
    grid = to_grid(series)
    filled, _ = fill_short_gaps(grid)
    return make_features(filled, grid)


# ---------------------------------------------------------------- the definitions
def test_tiers_are_nested_and_richest_first():
    f = features_with_target(hourly(24 * 20))
    all_cols = feature_columns(f)
    full, day, short = tier_defs(all_cols)
    assert [t["name"] for t in (full, day, short)] == [name for name, _, _ in TIERS] == ["full", "day", "short"]
    assert full["features"] == all_cols
    assert set(short["features"]) < set(day["features"]) < set(full["features"])
    assert not any(c in day["features"] for c in ("lag_48", "lag_144", "lag_168"))
    assert [c for c in short["features"] if c.startswith("lag_")] == ["lag_1", "lag_2", "lag_3"]
    assert full["needs_hours"] > day["needs_hours"] > short["needs_hours"]


# ---------------------------------------------------------------- the cascade, hour by hour after a hole
def test_cascade_picks_the_richest_tier_that_is_complete():
    start, last = 200, 204                                 # a 5-hour hole: positions 200..204 are missing
    f = features_with_target(hourly(24 * 20, holes=range(start, last + 1)))
    chosen = assign_tiers(f, tier_defs(feature_columns(f)))
    at = lambda k: chosen.iloc[last + k]                   # k hours after the last missing hour

    assert all(chosen.iloc[p] is None for p in range(start, last + 1))    # no reading, no forecast
    assert at(1) is None and at(2) is None and at(3) is None              # lag 1, 2, 3 still inside the hole
    assert at(4) == "short"                                # 3 clean hours behind it: the short tier is back
    assert at(7) == "full"                                 # every lag lands outside the hole
    assert at(10) == "short"                               # the 12 h lag lands in the hole
    assert at(22) == "short"                               # the 24 h lag lands in the hole
    assert at(30) == "full"
    assert at(46) == "day"                                 # only the 48 h lag is missing: the day tier does not need it
    assert at(142) == "day" and at(166) == "day"           # same for the 144 h and 168 h lags
    assert chosen.iloc[start - 1] == "full"                # the hour before the outage is untouched


def test_with_one_tier_the_same_hole_costs_far_more_hours():
    f = features_with_target(hourly(24 * 20, holes=range(200, 205)))
    defs = tier_defs(feature_columns(f))
    after = slice(205, 205 + 170)                          # the week after the hole
    with_fallback = assign_tiers(f, defs).iloc[after].notna().sum()
    full_only = assign_tiers(f, defs[:1]).iloc[after].notna().sum()
    assert with_fallback == 170 - 3                        # only the first three hours are lost
    assert full_only == 170 - 31                           # alone, the full model loses 31: each of its nine
                                                           # lags lands in the 5-hour hole in turn


# ---------------------------------------------------------------- the model file with tiers
def test_every_tier_in_the_file_reproduces_sklearn():
    f = features_with_target(hourly(24 * 420, holes=list(range(3000, 3010)) + list(range(7000, 7030))))
    defs = tier_defs(feature_columns(f))
    spec, fitted = build_tiered_spec(f, defs, version="vtest", sensor_id=42)
    again = json.loads(json.dumps(spec))                   # as it will be read back from disk
    assert [t["name"] for t in tiers_of(again)] == ["full", "day", "short"]
    for tier in tiers_of(again):
        model, rows = fitted[tier["name"]]
        point, lower, upper = predict(tier, rows, clip=False)
        assert np.allclose(point.to_numpy(), model.predict(rows[tier["features"]]), atol=1e-8)
        assert (lower <= point).all() and (point <= upper).all()
    rows_per_tier = [fitted[n][1].shape[0] for n in ("full", "day", "short")]
    assert rows_per_tier == sorted(rows_per_tier) and rows_per_tier[0] < rows_per_tier[-1]   # fewer lags, more rows


def test_a_v1_file_reads_as_one_full_tier():
    f = features_with_target(hourly(24 * 420)).dropna()
    spec, _ = build_spec(f, feature_columns(f), version="v1")
    tiers = tiers_of(spec)
    assert len(tiers) == 1 and tiers[0]["name"] == "full" and tiers[0]["features"] == spec["features"]
    a, _, _ = predict(tiers[0], f.iloc[:50])
    b, _, _ = predict(spec, f.iloc[:50])
    assert (a.to_numpy() == b.to_numpy()).all()


def test_the_hourly_job_falls_back_after_a_gap_instead_of_going_silent():
    train = features_with_target(hourly(24 * 420, holes=list(range(3000, 3010)) + list(range(7000, 7030))))
    spec, _ = build_tiered_spec(train, tier_defs(feature_columns(train)), version="vtest", sensor_id=42)

    now = pd.Timestamp("2026-11-12 06:10", tz="UTC")
    n = 24 * 20
    idx_end = now.floor("h") - pd.Timedelta(hours=3) + pd.Timedelta(minutes=30)
    recent = hourly(n, start=idx_end - pd.Timedelta(hours=n - 1))
    recent = recent.drop(recent.index[n - 20:n - 12])      # an 8-hour outage that ended 12 hours ago
    table, counts = forecast_table(spec, feature_rows(recent), now)

    # the 22 origin hours in the window: 2 before the outage, 8 inside it, 12 after it
    assert counts["in_window"] == 22
    assert counts["full"] == 2                             # v1 would have stopped here: only the hours before the outage
    assert counts["short"] == 9 and counts["day"] == 0     # v2 forecasts 9 of the 12 hours after it
    assert counts["none"] == 8 + 3                         # no reading (8), and the first three hours after
    assert len(table) == 11 and list(table["tier"]) == ["full"] * 2 + ["short"] * 9
    assert table[["point", "lower", "upper"]].notna().all().all()
    assert (table["target_time"] - table["origin_time"] == pd.Timedelta(hours=24)).all()


def test_an_existing_model_file_is_never_silently_replaced(tmp_path):
    used = tmp_path / "v1.json"
    used.write_text("{}")
    with pytest.raises(SystemExit):
        check_not_overwriting(used)                        # the 13 Nov mistake: a refit saved over v1
    check_not_overwriting(used, overwrite=True)            # allowed only when asked for explicitly
    check_not_overwriting(tmp_path / "v9.json")            # a new version is always fine


# ---------------------------------------------------------------- the evaluation
def test_evaluation_scores_each_tier_on_common_and_served_rows():
    holes = [p for s in range(400, 24 * 560, 700) for p in range(s, s + 7)]     # a 7-hour outage every ~29 days
    f = features_with_target(hourly(24 * 560, holes=holes))
    comparison, availability, oos = evaluate_tiers(f)

    t = comparison.set_index("tier")
    assert list(comparison["tier"]) == ["full", "day", "short", "cascade (v2)", "full only (v1)"]
    assert t.loc["full", "n_common"] == t.loc["day", "n_common"] == t.loc["short", "n_common"]   # same rows compared
    assert t.loc["full", "n_served"] == t.loc["full", "n_common"]
    assert t.loc["day", "n_served"] > 0 and t.loc["short", "n_served"] > 0       # the fallbacks do get used
    assert t.loc["cascade (v2)", "n_served"] == t.loc[["full", "day", "short"], "n_served"].sum()
    assert t.loc["cascade (v2)", "n_served"] > t.loc["full only (v1)", "n_served"]

    hours = list(availability["hours"])
    assert hours == sorted(hours) and hours[-1] > hours[0]                       # each tier adds hours
    assert availability["share_of_grid_hours"].iloc[-1] <= 1.0
    served = oos["served"].dropna()
    assert set(served.unique()) <= {"full", "day", "short"}
