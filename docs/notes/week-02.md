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

## What I couldn't explain yet (draft - rewrite in my own words)

1. **Why ridge beat boosting.** Boosting is many small decision trees. A tree answers with the average
   of the training rows that look like the current one, so it can never give a number higher than what
   it saw in training. For fold 1 the training data (Feb-Nov 2025) sat between 15 and 60; the winter
   then went to around 100. Boosting kept answering "about 60" and scored 24.8. Ridge is a weighted
   sum of the lags: a bigger input gives a bigger output, with no ceiling. It scored 15.0 in that fold.
   Teaching boosting to predict the 24 h change instead of the level helped (20.2) but not enough.
   Over all six folds ridge is 8.66 against 9.36 for persistence.

2. **Why the fold-6 band covered only 60%.** The fixed-width band takes its width from the model's
   errors in the 8 weeks before the fold. Before fold 6 those weeks were monsoon: clean air, small
   errors, so the narrowest band of all six folds (13.9 against 28-46 in folds 1-4). Fold 6 itself was
   mid-September to early November, when pollution and errors rise. The band was too narrow for that,
   so only 60% of actual values fell inside. Fold 1 failed the same way a year earlier (0.65). The ratio
   band gets wider when the forecast is higher, so it follows the season: worst fold 0.73, mean 0.82.
   (Checked in results/intervals.csv.)

3. **What the 24 h gap in the splits prevents.** Every training row's answer is the reading 24 hours
   later. If training ended exactly where the test window starts, the answers of the last 24 training
   rows would be readings from inside the test window, so the model would have seen part of the exam.
   Stopping training 24 hours before the test starts means no training answer comes from the test period.

## Carried into week 3

- 9 Nov: v1 live (table, JSON model, hourly step). 10 Nov: the API. First 13 live hours, the day after
  Diwali: MAE 33.2, bias -24.6, coverage 0.615, persistence 46.3.
- Availability failure on day one: after the Diwali-night gap, 24 h with no complete feature row and no
  forecasts. Fix on 11 Nov: fallback tiers on shorter lags.
