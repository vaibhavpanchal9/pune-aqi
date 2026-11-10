# Week 2 — 2 to 8 November 2026

## What got built

- **The data as the model sees it** (`dataset.py`): one row per hour on a regular grid, value policy and
  gap policy as code, lags 1-168 h, rolling means, IST time features, target = the unfilled value 24 h
  later. 15,071 grid hours, 10,186 usable rows. 88 readings removed by the value policy (83 zeros,
  72 flat-run hours, 5 dropouts, overlapping), 263 short-gap hours filled, 1,199 hours still missing.
- **A fair test** (`splits.py`, `evaluate.py`): six walk-forward folds of 8 weeks each, expanding
  training window, 24 h gap between train and test. Persistence is the benchmark: mean MAE 9.36 µg/m³.
  (On the last 8 weeks alone it was 7.99 — one window flatters; six seasons do not.)
- **Models** (`train.py`): ridge on all features 8.66 (7.5% better than persistence). Gradient boosting
  lost: 24.8 in the first winter fold where the linear model scored 15.0; predicting the 24 h change
  instead of the level brought it to 20.2, still behind. Ridge is v1.
- **Where it fails** (`error_analysis.py`): persistence beats ridge in 4 of 26 slices, all at high
  levels — Poor-or-worse hours: ridge 24.7 vs persistence 18.6.
- **A band around the number** (`intervals.py`): three 80% methods; residual-ratio chosen — coverage
  0.821, worst fold 0.73, mean width 35.9, Poor+ coverage 0.516.
- **The pipeline, measured** (`sql/10_gate1_evidence.sql`): 47 unattended runs by 7 Nov, 0 failures,
  longest gap 11 h. Then the hourly timer via cron-job.org (HTTP 204): 4 runs a day became 27.
- 51 tests. Repository made public on 8 Nov after a history scan for secrets (clean).

## What I learned

- A benchmark on one window is not a benchmark. 7.99 became 9.36 when six seasons were used.
- Trees cannot extrapolate: asked about a December at 100 µg/m³ after training on 15-60, boosting
  answers "about 60". A straight line through the lags does not have that problem.
- A selection rule can pick the wrong thing: "closest mean coverage" chose a band whose per-fold
  coverage swung from 0.60 to 0.97. Rule changed to: honest on average AND smallest worst-fold miss.
- GitHub's cron is best-effort (about 4 of 24 slots a day). The fix is a timer outside GitHub that
  calls the API with a token that can do one thing only.
- Private repositories meter Actions minutes and hide the resume link. Public, after checking history.

## What went wrong

- Wrote the interval selection rule before looking at the per-fold numbers; the first pick was wrong.
- Re-ran an old Actions run instead of starting a new one; a re-run uses the old commit.
- `.gitignore` had `models/` in it, which would have hidden the model file (caught on 9 Nov).
- Week-02 notes written on 10 Nov, not Sunday.

## What I couldn't explain yet (rewrite in my own words)

1. **Why ridge beat boosting.** Boosting predicts by averaging the training rows that look most like the
   current one; it can never output a value outside the range it was trained on. Winter 2025 levels were
   higher than anything before them, so every tree answered with the highest value it knew. Ridge
   multiplies the lags by fixed weights, so a higher input simply gives a higher output.

2. **Why the fold-6 band covered only 60%.** The residual-quantile band has a fixed width in µg/m³,
   measured on the 8 weeks before the fold. Fold 6 was a quieter period than its calibration weeks, so the
   width was right for the wrong level: too wide where it did not matter and, at the hours that jumped,
   still too narrow. The ratio band scales with the forecast, which is why its folds vary less.

3. **What the 24 h gap in the splits prevents.** The target of the last training row is the value 24 h
   later. Without the gap, that value lies inside the test window: the model has seen a test answer during
   training. The gap pushes the training window back far enough that no training target falls in test.

## Carried into week 3

- 9 Nov: v1 live (table, JSON model, hourly step). 10 Nov: the API. First 13 live hours, the day after
  Diwali: MAE 33.2, bias -24.6, coverage 0.615, persistence 46.3.
- Availability failure on day one: after the Diwali-night gap, 24 h with no complete feature row and no
  forecasts. Fix on 11 Nov: fallback tiers on shorter lags.
