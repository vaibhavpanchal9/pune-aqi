"""Out-of-sample predictions cover every test row exactly once; slices add up to the whole."""

import pandas as pd

from evaluate import predictions, persistence
from splits import walk_forward
from error_analysis import slice_table, label, BANDS, TIME_OF_DAY
from tests.test_train import synthetic_features


def test_predictions_cover_every_test_row_once():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=3, test_weeks=4, min_train_days=90)
    p = predictions(persistence, f, folds)
    expected = pd.Index([]).append([te for _, te in folds])
    assert len(p) == len(expected)
    assert p.index.equals(expected.sort_values())
    assert not p.index.has_duplicates


def test_slices_add_up_to_the_whole():
    f = synthetic_features()
    folds = walk_forward(f.index, n_folds=2, test_weeks=4, min_train_days=90)
    df = pd.DataFrame({"y": f["y"]})
    df["yhat_model"] = predictions(persistence, f, folds)
    df["yhat_bench"] = predictions(persistence, f, folds)
    df = df.dropna()
    df["level"] = [label(v, BANDS) for v in df["y"]]
    t = slice_table(df, "level")
    assert t["n"].sum() == len(df)
    assert (t["winner"] == "persistence").all()          # identical forecasts: model never strictly wins


def test_labels_are_exhaustive():
    assert label(0, BANDS).startswith("1") and label(30, BANDS).startswith("2")
    assert label(89.9, BANDS).startswith("3") and label(500, BANDS).startswith("4")
    assert label(0, TIME_OF_DAY).startswith("night") and label(23, TIME_OF_DAY).startswith("evening")
