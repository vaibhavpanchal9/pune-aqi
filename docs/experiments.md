# Experiments — Step 8, 3 Nov 2026

All on `python train.py`: six walk-forward folds (docs/validation.md), MAE in µg/m³, Pashan, 10,138
usable rows, 21 features. Two runs produce byte-identical CSVs (`results/model_comparison.csv`).

| model | 1 (winter) | 2 | 3 | 4 | 5 | 6 (autumn) | mean |
|---|---|---|---|---|---|---|---|
| ridge | 15.39 | 10.36 | 9.42 | 5.22 | 4.43 | 7.13 | **8.66** |
| ridge_lags_only | 15.44 | 10.58 | 9.61 | 5.27 | 4.46 | 7.11 | 8.75 |
| blend_ridge_hgb | 16.65 | **10.18** | **9.25** | **4.87** | 4.21 | 7.83 | 8.83 |
| persistence (benchmark) | **14.95** | 11.31 | 10.73 | 5.91 | 5.25 | 7.99 | 9.36 |
| hgb_all_delta | 20.15 | 10.74 | 9.39 | 4.92 | 4.18 | 9.26 | 9.77 |
| hgb_all | 24.81 | 10.86 | 9.01 | 4.96 | 4.15 | 9.67 | 10.58 |
| mean_24h | 20.97 | 14.39 | 11.02 | 5.38 | 4.45 | 8.10 | 10.72 |
| hgb_lags_only | 26.39 | 11.50 | 9.51 | 5.08 | 4.29 | 8.56 | 10.89 |
| hgb_all_logratio | 28.13 | 10.91 | 9.22 | 4.99 | 4.18 | 10.91 | 11.39 |
| hgb_all_delta_sq | 36.52 | 10.88 | 9.31 | 5.13 | **4.13** | 8.89 | 12.48 |
| climatology | 29.01 | 15.87 | 11.03 | 5.67 | 4.10 | 14.13 | 13.30 |
| weekly_naive | 24.52 | 19.18 | 14.97 | 7.66 | 5.57 | 10.93 | 13.80 |

## What worked
- **Ridge on all features: 8.66, 7.5% under the benchmark, best or near-best in every fold.** A linear
  model extrapolates; the winter fold asks for exactly that.
- Predicting the change instead of the level (`delta`) cut boosting's winter error from 24.8 to 20.2
  and its mean from 10.58 to 9.77. Right direction, not enough.
- The blend of ridge and boosting-delta wins folds 2–5 — every season the training data had already
  seen once. It loses folds 1 and 6 because boosting does.

## What did nothing, or worse
- Log-ratio formulation: worse than delta everywhere (28.1 in winter).
- Squared-error loss for boosting: 36.5 in winter. Absolute error was the right loss for this target.
- Boosting on lags only vs all features: no help; the time features matter slightly for both models.

## Why boosting loses the winter fold
Fold 1 trains on Feb–Nov 2025 and is tested on Dec–Jan at 60–120 µg/m³, levels absent from training.
Trees answer with the highest targets they have seen; they cannot extrapolate. Ridge can. In fold 2,
with one month of winter in training, both ridge (10.36) and boosting-delta (10.74) beat persistence
(11.31). Fold 1 is a statement about the first winter in the record, not about the model that ships
in December 2026, which will have last winter in its training rows. It stays in the mean anyway.

## Decision
Ship **ridge** as the v1 product model (decisions.md, 2026-11-03). Revisit the blend when a second
winter exists in the data.
