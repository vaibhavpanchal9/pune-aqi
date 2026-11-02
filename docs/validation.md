# Validation — how every forecaster in this project is scored

## Not a random split
Hourly PM2.5 rows are not independent: 10:00 and 11:00 share nearly all their information. A random
train/test split would quiz the model on hours it has effectively already seen, and the score would be
flattering and meaningless. Forecasters are tested the way they are used: on hours after everything they
learned from.

## Walk-forward, expanding window, 24-hour gap

                 |<-------------- train ------------->| gap |<-- test k -->|
    ...----------+------------------------------------+-----+--------------+------------
                                                                           |<-- test k+1 -->| ...

- The target of origin hour t is the value at t + 24 h. Without a gap, the last training rows' targets
  would sit inside the test window. The gap is 24 hours, between the last training origin and the first
  test origin.
- Six consecutive 8-week test windows, counted back from the newest usable hour (48 weeks in all), each
  trained on everything before it. They cover last winter's peak, the spring decline, the monsoon floor
  and this autumn's rise. Five 4-week windows (the original plan) would have tested June–October only
  and never met a winter.
- Windows are defined by timestamps, not row positions, so missing hours cannot shift them; a hole just
  means fewer rows in that fold (fold 2 below: the 11–19 Jan 2026 outage).

## The folds on Pashan (`python splits.py`, 3 Nov 2026)

```
 fold                train_from                  train_to  train_rows                 test_from                   test_to  test_rows  gap_hours
    1 2025-02-25 19:30:00+00:00 2025-11-26 14:30:00+00:00        4353 2025-11-27 15:30:00+00:00 2026-01-09 11:30:00+00:00       1015       25.0
    2 2025-02-25 19:30:00+00:00 2026-01-09 11:30:00+00:00        5392 2026-01-27 14:30:00+00:00 2026-03-19 14:30:00+00:00        673      435.0
    3 2025-02-25 19:30:00+00:00 2026-03-18 14:30:00+00:00        6041 2026-03-19 15:30:00+00:00 2026-05-14 11:30:00+00:00       1085       25.0
    4 2025-02-25 19:30:00+00:00 2026-05-13 11:30:00+00:00        7133 2026-05-14 19:30:00+00:00 2026-07-09 14:30:00+00:00       1064       32.0
    5 2025-02-25 19:30:00+00:00 2026-07-08 14:30:00+00:00        8190 2026-07-09 15:30:00+00:00 2026-09-02 08:30:00+00:00       1024       25.0
    6 2025-02-25 19:30:00+00:00 2026-09-02 08:30:00+00:00        9238 2026-09-05 00:30:00+00:00 2026-10-29 14:30:00+00:00        900       64.0
```

Fold 1 (27 Nov → 9 Jan) is the hardest: the winter peak, with no previous winter in the training rows.
Fold 2 is short (673 rows, 435 h gap) because of the January outage; its dates did not move.
Fold 6 is the window the Step 6 baselines were scored on (persistence MAE 7.99).

## Enforced by tests/test_splits.py
Train strictly before test with the gap · folds consecutive and non-overlapping · training window
expands from the same start · holes in the data do not move the windows · too little history is refused.