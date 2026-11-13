# Decisions log

One entry per real decision. Date it. Say what you chose and why you rejected
the alternative. This file is where interview answers come from.

---



## 17 Aug 2026 — Store UTC, convert to IST only for display

`measured_at` is `TIMESTAMPTZ` holding UTC. OpenAQ returns both `utc` and
`local` for every timestamp; the parser deliberately reads only `utc`.

Why: FILL THIS IN — Day 2, task 9, in your own words. Cover what would break in
the hour-of-day feature if local time leaked in.

---



## 17 Aug 2026 — Primary key is (sensor_id, measured_at, source)

Rejected: a surrogate `id` column with a separate unique constraint.

Why: FILL THIS IN. Cover why this makes both the hourly job and the backfill
safe to re-run.



## 2026-10-26 — cloud ingest live; resume clock starts

GitHub Actions `ingest.yml` (cron 23 */2 UTC) first fired on its own on 26 Oct 2026 at __:__ UTC,
writing to Neon. "Days running" on the resume counts from this date; the proof is
`SELECT min(run_at) FROM ingestion_runs WHERE status = 'ok'` — manual runs on the same day
don't change the date.

Upstream note: OpenAQ's Pune feed (all 13 live sensors) stopped at 2026-10-23 14:30 UTC.
Our job has run every 2 h since 26 Oct and found nothing new; healthcheck reports it as
UPSTREAM LAG, not as our failure. Track the gap in docs/data_quality.md (Step 5).



## 2026-10-29 — features are computed on a regular hourly grid, never on raw rows

`LAG(value, 24)` means "24 rows back". On the raw measurements table that is 24 hours back only
when nothing is missing in between — and 9.2% of Pashan's hours are missing. Measured on 4 Feb 2026,
after a 17-hour gap: the "24-row" average reached 41 hours back and said 80.4; the true 24-hour
average was 88.5. Decision: every lag, rolling mean and target is computed on a grid with one row
per hour (`generate_series` in `v_features`; `asfreq('h')` in pandas), where a missing hour is a NULL
row. Rows == hours, so row arithmetic is time arithmetic. Verified: `lag_24` equals the reading 24 h
earlier on all 13,452 checkable rows (sql/09_v_features.sql, Q36).

## 2026-10-29 — indexes: look before adding
`idx_measurements_time (measured_at)` has existed since August; it makes `max(measured_at)` an Index
Only Scan Backward (0.03 ms) and the "last N days across stations" query 2.4 ms vs 183 ms as a Seq
Scan. A duplicate index added today was dropped; `idx_measurements_sensor` was dropped too because
it is a prefix of the primary key. Rule: read `pg_indexes` and the EXPLAIN plan before CREATE INDEX.



## 2026-10-30 — value policy (applied in dataset.py before anything else)

Numbers from `quality_report.py`, sections C and D, 30 Oct 2026. A reading becomes NULL (= missing) if:
1. `value < 0` — physically impossible. 8 rows, all Park Street Wakad; 0 at Pashan.
2. `value = 0` — PM2.5 in Pune is never exactly zero; zeros come in flat runs (Nigdi 31 runs,
   Pashan 6 runs of 0.0), i.e. a stuck instrument. 83 rows at Pashan (0.6%).
3. `value >= 985` — the instrument ceiling is 1000; 985+ is "off scale". 5 rows table-wide, 0 at Pashan.
4. The reading belongs to a run of 6 or more identical consecutive values — a frozen sensor
   (Revenue Colony: 191 h at 225.1; Hadapsar: 121 h at 10.6). The whole run becomes NULL.
   At Pashan every such run is 0.0 and already caught by rule 2.
5. The reading is more than 4× above or below BOTH neighbours (spike / dropout). 5 rows at Pashan,
   e.g. 2026-02-03 07:30 (90.3 → 13.0 → 52.1). Thresholds are deliberately loose: a real Diwali-night
   spike is 2–3×, not 4×, and a false positive here costs one hour of training data, not a forecast.
Nothing is ever edited or replaced with a guess; it is removed, and the gap policy decides the rest.



## 2026-10-30 — gap policy (hourly grid; what is filled, what is excluded)

From `quality_report.py` section A, Pashan: 1,354 missing hours — 202 in 163 gaps of 1–2 h, 87 in
25 gaps of 3–5 h, 380 in 33 gaps of 6–23 h, 685 in 8 gaps of a day or more.
1. Readings are placed on a regular hourly grid; a missing hour is a NULL row (see 2026-10-29).
2. A gap of **at most 3 consecutive missing hours is forward-filled** (the last reading carried
   forward). Justification: hour-to-hour change at Pashan is typically ±10 against levels of 20–100
   (Q21), so a 1–3 h carry is a small error; beyond 3 h the daily cycle moves (the 9–10 am peak,
   the 4 pm trough) and a flat carry becomes wrong. This touches at most ~290 of the 1,354 missing
   hours (≈ 21%).
3. **Gaps longer than 3 hours stay NULL.** Any training or evaluation row whose



## 2026-11-01 — the benchmark

Four baselines scored on the last 8 weeks of usable rows at Pashan (5 Sep → 29 Oct 2026, 900 rows,
24 h gap before the test window; `results/baselines.csv`, `python baselines.py`):
persistence MAE 7.99 · mean of last 24 h 8.10 · weekly naive 10.93 · climatology 14.13.
**The benchmark is persistence, MAE 7.99 µg/m³.** Step 8's models are judged against it on the same
rows; Step 7 replaces this single window with five walk-forward folds, and the benchmark becomes the
best baseline's mean across folds. All four biases are negative because the window is a rising season;
climatology (−13.4) is one year of history pretending to be a climate, and is kept as a warning.




## 2026-11-03 — the benchmark, properly

Six walk-forward folds (docs/validation.md), four baselines, `python evaluate.py`,
`results/baselines_folds.csv`. Persistence wins the mean — **9.36 µg/m³** — and folds 1, 2, 3, 6;
in the two monsoon folds the mean of the last 24 h (5.38) and climatology (4.10) beat it. Fold 1
(winter peak, 27 Nov → 9 Jan) is the hardest: 14.95 for persistence, 29.01 for a climatology that
had never seen a winter. Every model in Step 8 is judged on these six folds through the same harness;
it must beat 9.36 on the mean, and the fold-1 number decides whether it is worth deploying.
The 2026-11-01 entry (7.99 on one autumn window) is superseded.



## 2026-11-03 — the v1 model is ridge regression

Eight models and four baselines through the same harness on six walk-forward folds
(`docs/experiments.md`, `results/model_comparison.csv`, deterministic). Ridge on all 21 features:
mean MAE **8.66 µg/m³ vs 9.36 for persistence, −7.5%**; best or within 0.5 of the best in every fold.
Gradient boosting is best in the three mid-year folds but cannot extrapolate into the first winter
(24.8; 20.2 predicting the change) and loses on the mean. The simple model wins, and the reason is
understood. The blend (ridge + boosting-delta, wins folds 2–5) is the candidate for v2 once a second
winter is in the data. Gate 1 condition (2) is met by ridge, not by boosting; the gate asked for a
model that beats the best baseline on walk-forward MAE, and this one does.



## 2026-11-07 — Gate 1 evidence (final check on 15 Nov)
`sql/10_gate1_evidence.sql`: first unattended run 2026-10-26 09:00 UTC; 11.9 days running; 47 live
runs, 0 failed; longest gap between successful runs 11 h 00 m (limit 12 h); mean gap 6.1 h (GitHub
delivers ~4 of 24 hourly slots). Condition (2): ridge 8.66 vs persistence 9.36 on six walk-forward
folds (docs/experiments.md). Both conditions hold; the 14-day mark falls on 9 Nov.



## 2026-11-07 — the v1 band is residual-ratio quantiles, 80% nominal

Three methods on six folds (`results/intervals.csv`, `python intervals.py`). Residual quantiles average
0.806 but swing from 0.60 to 0.97 across folds: errors measured on the previous season do not fit the
next one. Quantile regression is overconfident in five of six folds (0.73). Residual-ratio quantiles —
relative errors, so the band scales with the forecast — cover 0.82 on average, never below 0.73 in any
fold, and 52% of the Poor-or-worse hours (vs 37% and 33%). Width 36 µg/m³: honest, not pretty.
In production the calibration window is always the most recent 8 weeks before retraining, which is
the best any static band can do; v2 candidates are a rolling re-calibration and quantile boosting.
## 2026-11-09 — v1 goes live: ridge + residual-ratio band as JSON, one forecast per hour, never overwritten

**Decision 1 — the product model is a JSON file, not a pickle.** `fit_model.py` refits the Step 8 ridge on
every usable row (10,186 rows, 25 Feb 2025 -> 7 Nov 2026 17:30 UTC) and calibrates the Step 9 residual-ratio
band on the last 8 weeks (789 usable rows: lo_q -0.275, hi_q +0.401), then writes `models/v1.json`: 21 feature
names, 21 means, 21 scales, 21 coefficients, one intercept, the two quantiles, and where each number came from
(rows, dates, library versions, git commit, and the walk-forward MAEs read from results/model_comparison.csv:
8.657 vs persistence 9.357). `forecast.py` applies it with numpy alone.
*Why:* readable and diffable in git; serving needs no scikit-learn; a pickle ties the service to one library
version and runs code on load. `tests/test_forecast.py` proves the JSON reproduces scikit-learn to 1e-8 and
that `forecast.predict` equals `intervals.residual_band(ratio=True)` on unseen rows: the service serves
exactly what was evaluated.

**Decision 2 — one horizon, first forecast stands.** Every hour, after ingest, `forecast.py` issues a forecast
for each origin hour of the last 24 h that has a complete feature row and whose target hour is still ahead.
A row in `forecasts` is written once (`ON CONFLICT DO NOTHING`); point and band are clipped at 0.
*Why one horizon:* 24 h ahead is what was evaluated; 24 separate models would be 23 unevaluated ones (a v2
candidate). *Why never overwrite:* a forecast that stands is what a user would have been told, so
forecast-vs-actual (sql/11_forecasts.sql, Q43) is a true live score. *Why clipping is free:* it can only move
a number towards the actual, so the walk-forward MAE and the coverage still hold.

**Known limits, measured rather than hidden.**
1. Readings arrive late (the primary station was 11.3 h behind at the first run), so the newest forecast
   reaches 24 h minus the lag: 12.7 h on 9 Nov. Q42 tracks issue delay and lead time.
2. No forecast is issued when any feature is missing: a gap longer than 3 h removes rows at every lag offset
   after it. Q44 tracks availability. A fallback model on fewer lags is a v2 candidate.
3. The spike/dropout rule needs the next reading, so it cannot be applied to the newest hour at issue time:
   a spike there is forecast from, and only later removed from training data.
4. The first 13 forecasts were issued at 10:17 IST on 9 Nov and straddle Diwali night (8 Nov): the 23:00 IST
   forecast of 138 µg/m³ carries the festival reading forward. Q43 scores it on 10 Nov.

## 2026-11-10 — the API: three read-only endpoints, served sensor and model read from the model file

`app.py` (FastAPI, Pydantic models, /docs generated) over `service.py` (one function per endpoint,
one connection per request). `/health` reuses healthcheck.py's thresholds by importing them; `/forecast`
returns 200 with an empty list when nothing is on file, 404 for a sensor without a model, 422 for a
non-integer id; `/stats` puts the live record (as issued, never revised) next to the walk-forward figure.
The served sensor, version, horizon and band come from models/v1.json so the API cannot drift from
forecast.py. Tested at the HTTP layer with fakes (tests/test_api.py); the SQL is checked by
`python service.py` against Neon.

**First live day (results/live_2026-11-10.txt).** 13 hours scored, all on 9 Nov, the day after Diwali:
MAE 33.2, bias -24.6 (under-forecast), coverage 0.615, persistence MAE 46.3. Not a verdict; a record.

**Availability failure, day one.** After the Diwali-night gap the station came back, but for 24 h no
origin row had every lag present: 21 hours in the window, 0 complete, 0 forecasts issued. Fix planned
for 11 Nov: fallback tiers of the same ridge recipe on shorter lag sets, each evaluated on the same
six folds, used when the full row is incomplete.

## 2026-11-13 — v2: fallback tiers, so a gap costs hours instead of a day

**Problem (measured).** v1 needs every lag back to 168 h. After the Diwali-night gap it issued nothing for
24 h; on 13 Nov only 40 of the last 168 hours had a forecast (sql/11_forecasts.sql Q44). Over the 48 test
weeks the full feature row is complete for 73% of hours (80% of the hours the station reported).

**Decision.** Keep the full ridge and add two smaller ones of the same recipe: `day` (no 48/144/168 h
lags; needs 24 h of history) and `short` (no lag beyond 3 h; needs 3 h). Each hour forecast.py uses the
richest tier whose features are all present and records it in `forecasts.tier`. Missing lags are never
invented. Model file models/v2.json; v1 stays in the repository and its rows keep their version.

**The rule, written before the numbers.** A fallback tier ships only if it beats persistence on the hours
it would actually serve (no richer tier complete), out of sample.

**Evidence (tiers.py, six folds of 8 weeks, pooled; results/tier_comparison.csv, data to 12 Nov).**

| tier | hours served | MAE | persistence, same hours | band coverage there |
|---|---|---|---|---|
| full | 5,532 | 8.60 | 9.31 | 0.81 |
| day | 908 | 7.89 | 9.08 | 0.87 |
| short | 382 | 10.15 | 10.67 | 0.83 |
| cascade (v2) | 6,822 | 8.59 | 9.36 | |
| full only (v1) | 5,532 | 8.60 | 9.31 | |

Both fallbacks pass. `short` passes narrowly (5% better than persistence) and is kept because the
alternative is no forecast. On the hours all three can do, dropping lags costs little: 8.60 (full),
8.70 (day), 8.77 (short). The 48/144/168 h lags buy about 1%.

**What it buys (results/tier_availability.csv).** Hours that can be forecast over the 48 test weeks:
73% -> 86% -> 91% of all hours; 80% -> 93% -> 99% of the hours with a reading. 1,290 more forecast
hours (+23%) at the same MAE (8.59 vs 8.60).

**A number that moved, and why.** The full tier's mean-of-folds MAE is 8.91 here, not the 8.66 of 3 Nov
(results/model_comparison.csv). Same model, same recipe: the folds are anchored on the newest data, nine
more days have arrived, and the last fold now contains Diwali week. Every reported number therefore
carries its evaluation date. Before the v1.0 write-up the whole comparison is rerun once on a frozen end
date (splits.walk_forward now takes `end=`).

**v1's live record at the switch (results/live_2026-11-13.txt).** 37 hours scored, MAE 18.75 against
25.48 for persistence, coverage 0.757, starting with the day after Diwali.

**Mistake of the day, and the guard.** The first attempt ran the old fit_model.py (the new files had not
been downloaded) and replaced models/v1.json with a refit still named v1. Nothing was issued from it
(0 new rows) and the file was restored from git. fit_model.py now refuses to overwrite an existing model
file, with a test. Commands in a list are now chained with && so a failed step stops the rest.
