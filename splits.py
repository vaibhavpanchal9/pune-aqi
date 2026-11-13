"""Step 7 (1/2). Walk-forward splits: train on the past, test on the future, with a gap. Several times.

    from splits import walk_forward
    folds = walk_forward(features.index)          # list of (train_index, test_index) pairs

Why not a random split: a row at 10:00 and a row at 11:00 share almost all their information. Shuffle
them into train and test and the model is quizzed on hours it has effectively seen -- the score looks
wonderful and means nothing. Time-series models are tested the way they will be used: on hours that
come AFTER everything they learned from.

Why a gap: the target of an origin hour t is the value at t + 24 h. If training may run right up to the
test window, the last training rows' targets sit INSIDE the test window. A 24-hour gap between the last
training origin and the first test origin removes that leak. (Step 6 does the same for the baselines.)

Why several folds, and why these sizes: one test window is one season, and Pune has two very different
ones (Pashan: 16-20 ug/m3 from May to September, 58-70 from December to February). Six consecutive
8-week windows reach back 48 weeks from the newest hour, so the folds cover last winter's peak, the
spring decline, the monsoon floor and this autumn's rise. Each fold trains on everything before it (an
expanding window). Five 4-week folds -- the plan's original shape -- would have tested June to October
only and never met a winter.

                 |<-------------- train ------------->| gap |<-- test k -->|
    ...----------+------------------------------------+-----+--------------+------------
                                                                           |<-- test k+1 -->| ...

The function works on timestamps, not row positions, so missing hours on the grid cannot shift a fold.
"""

import pandas as pd


def walk_forward(index, n_folds=6, test_weeks=8, gap_hours=24, min_train_days=180, end=None):
    """Return a list of (train_index, test_index) DatetimeIndex pairs, oldest fold first.

    index           the DatetimeIndex of the rows available (usually the usable rows' index)
    n_folds         how many consecutive test windows, counted back from the newest timestamp
    test_weeks      length of each test window
    gap_hours       hours between the last training timestamp and the first test timestamp
    min_train_days  the oldest fold must still have at least this much training history, else ValueError
    end             where the newest window ends. Default: the newest timestamp in `index`. Pass the
                    same `end` to cut a DIFFERENT set of rows into the SAME windows in time (tiers.py
                    does this, so a model with more usable rows is tested on the same eight-week spans).
    """
    idx = pd.DatetimeIndex(index).sort_values()
    if idx.has_duplicates:
        raise ValueError("index has duplicate timestamps")
    end = idx.max() if end is None else end
    folds = []
    for k in range(n_folds):                      # k = 0 is the newest window
        test_end = end - pd.DateOffset(weeks=test_weeks * k)
        test_start = test_end - pd.DateOffset(weeks=test_weeks)
        train_end = test_start - pd.DateOffset(hours=gap_hours)
        test = idx[(idx > test_start) & (idx <= test_end)]
        train = idx[idx <= train_end]
        if len(train) == 0 or (train.max() - idx.min()) < pd.Timedelta(f"{min_train_days}D"):
            raise ValueError(f"fold {n_folds - k}: only {len(train)} training rows before {test_start}; "
                             f"need at least {min_train_days} days of history")
        folds.append((train, test))
    return list(reversed(folds))                  # oldest first, so fold 1 is the earliest test window


def describe(folds):
    """One row per fold: train range and size, test range and size. For docs and for your own eyes."""
    rows = []
    for i, (tr, te) in enumerate(folds, start=1):
        rows.append({"fold": i,
                     "train_from": tr.min(), "train_to": tr.max(), "train_rows": len(tr),
                     "test_from": te.min(), "test_to": te.max(), "test_rows": len(te),
                     "gap_hours": (te.min() - tr.max()) / pd.Timedelta("1h")})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse
    from baselines import load_features
    from dataset import PRIMARY, usable

    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()
    f = usable(load_features(args.sensor))
    d = describe(walk_forward(f.index))
    pd.set_option("display.width", 160)
    print(d.to_string(index=False))
