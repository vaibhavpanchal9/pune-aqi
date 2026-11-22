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

## 2026-11-15 — Gate 1: passed

**Condition 1: the cloud job has run unattended for 14+ days with no gap over 12 hours.** Met.
results/gate1_2026-11-15.txt: first run 26 Oct 09:00 UTC, 19.8 days, 246 runs, 0 failed, longest gap
11 h 00 m (30 Oct). All ten longest gaps are from before 8 Nov, when GitHub's own schedule was the only
trigger; since the external timer there are 28 runs a day.

**Condition 2: a model beats the best baseline on the walk-forward test.** Met. Ridge 8.66 vs
persistence 9.36 µg/m³, mean of six folds, data to 3 Nov (results/model_comparison.csv); v2 cascade
8.59 vs 9.36, pooled over six folds, data to 12 Nov (results/tier_comparison.csv).

**What the gate does not say (results/live_2026-11-15.txt).** The live record is running well behind
the test record:

| | scored hours | MAE | persistence, same hours | coverage of the 80% band |
|---|---|---|---|---|
| v1, 9-14 Nov | 61 | 19.2 | 22.5 | 0.69 |
| v2, 13-15 Nov | 48 | 22.4 | 23.4 | 0.50 |

Both still beat persistence, v2 only just. These are the days after Diwali with levels around 60-100,
the range where error analysis found the model weakest, and the forecasts run 8-10 µg/m³ low: the season
is rising and the band was calibrated on calmer weeks (the fold-1 / fold-6 failure, in milder form).
48 consecutive hours are about two days of independent evidence, so no change is made on this.
**Checkpoint: 29 Nov (Gate 2), with about 300 scored hours.** If live coverage is still under 0.70 the
band calibration is revisited before the write-up; the write-up reports live next to walk-forward
either way.

**The tiers, two days after shipping.** Since v2 (13 Nov) every hour has had a forecast (24/24, 24/24,
11/11 so far today; Tue 10 Nov had none). From Sunday 00:00 IST the `day` tier is serving: the 144-hour
lag has reached the Diwali-night gap, the "again six days later" hole in which v1 would have gone silent.

## 2026-11-16 — the API in a container

Dockerfile (three stages: base, test, runtime), docker-compose.yml (a local Postgres on 127.0.0.1:5433
plus the API; a `cloud` profile for the same image against Neon), seed_local.py (copies a month from Neon
into the local database and refuses any target that is not on this machine). Commands in docs/docker.md.

Choices: (1) the image holds only the API. No pandas or scikit-learn, because the model is JSON and the
forecasts are in the table: 250 MB on disk, 55 MB compressed. (2) The tests run inside the build, and the
runtime stage copies a marker from the test stage: no passing tests, no image. (3) Non-root user; `.env`
is excluded from the build context; secrets arrive as environment variables at start. (4) The container
health check asks `/`, not `/health`: a database query every 30 s would keep the free-tier database
awake. (5) Host ports are bound to 127.0.0.1; the local database password in the compose file is for the
throwaway container only and is not a secret.

First run: build 20.7 s, 8 passed in 0.36 s inside the container, `/health` "ok" from the cloud profile
and from the local stack after seeding (19 locations, 215 sensors, 7,169 readings, 298 runs, 160
forecasts). Live record on the same day, v2 after 75 scored hours: MAE 18.4 vs persistence 19.3,
coverage 0.57; first 9 hours of the `day` tier: 7.6 vs 4.8. Checkpoint stays 29 Nov.

## 2026-11-18 — the API is public: https://pune-aqi-api.onrender.com

Render free web service in Singapore (the database's region), built from the Dockerfile by `render.yaml`.
Gate 2's condition (the service live on a public address, returning forecasts with bounds) is met on
18 Nov; the formal check stays on 29 Nov together with the live-record checkpoint.

Choices: (1) **least privilege.** The API logs in as `aqi_api`, which can SELECT five tables and nothing
else (make_readonly_role.py; a DELETE is refused, checked by the script). The owner credentials stay with
the ingestion job. (2) **A short cache** in service.py (30 s health, 60 s forecast, 300 s stats): forecasts
change once an hour, and without it every public request would open a database connection. Errors are
never cached. (3) **Infrastructure in the repository:** render.yaml holds everything except the one
secret, which is typed into Render once. (4) **Build filter:** only changes to files inside the image
trigger a build. (5) Health check on `/`, not `/health`.

First latency (results/latency_2026-11-17.csv, from Pune, service awake): p50 about 180 ms and p95
between 250 and 320 ms on every endpoint. Known limit: the free host sleeps after 15 idle minutes and
takes about a minute to wake; to be measured.

## 2026-11-18 — CI, coverage, and two clocks for latency

**CI (.github/workflows/ci.yml).** Every push that changes code runs pyflakes and the whole suite on
Python 3.12 (the cloud job and the image) and 3.14 (the development machine), and builds the Docker
image, whose own build runs the API tests. Green on the first run. Pushes that touch only docs, notes,
results or figures are skipped. The hourly `ingest` workflow was left untouched: its unattended record
matters more than clearing a deprecation warning.

**Coverage: 36.4% of 1,809 statements, 81 tests.** The split is the point: the calculation and decision
code is covered (metrics and app 100%, transform 80%, tiers 76%, dataset 71%); everything that talks to
the database or the internet, and the command-line wrappers, is at or near 0%. No file is excluded to
improve the figure. CI fails below 35% so it cannot slide. Next: tests against a real Postgres in CI,
because no SQL statement has an automatic test yet.

**requirements.txt** was stale (pandas 3.0.3 pinned, 3.0.5 installed; numpy, matplotlib, pyflakes
missing). Regenerated from the environment; CI installs exactly these 13 pins.

**Latency.** A morning run showed 2 s per request against 180 ms the night before. `curl -w` showed a
1.4 s round trip on that network: three round trips, no server time. The API now sends a `Server-Timing`
header and bench.py reports both clocks: about 1 ms from memory, 44-81 ms with a database query, 617 ms
when the database is asleep too; 260 ms end to end that evening. Cold start of the free host: 14-25 s,
measured three times.

## 2026-11-19 — the SQL gets tests: a real Postgres, on the laptop and in CI

**The hole.** Until today no test touched a database. The API routes were tested with fake queries,
and the SQL itself was only ever checked by hand (`python service.py`, `runsql.py`). The coverage table
of 18 Nov showed it: `db.py` 20%, `ingest.py` 0%, `openaq_client.py` 0%, `service.py` 56%.

**What was added.** 51 tests, 81 → 132 (commit de2ec40). How to run them: `docs/testing.md`.

- `tests/test_db_integration.py` (25): applies `schema.sql` to an empty Postgres and runs the real
  queries. Readings are saved once however often they are offered; an ingest run ends with the right
  row in `ingestion_runs` (ok / partial / failed); `forecast.py` end to end; the queries behind
  `/forecast`, `/stats` and `/health`; the copy to a local database; the read-only role.
- `tests/test_openaq_client.py` (17): what the client retries (network errors, 429, 5xx), what it never
  retries (401, 410, 422), how long it waits, and paging. No internet: `requests.get` and `time.sleep`
  are replaced.
- `tests/test_local_tools.py` (9): `.env` is only ever changed one line at a time, the copy script only
  writes to this machine, and which request "p95" is.

**Decisions.**

1. A real Postgres, not a mock and not SQLite. What needs testing is Postgres behaviour itself:
   `ON CONFLICT DO NOTHING`, the foreign key, `DISTINCT ON`, `generate_series` in `v_features`, what a
   role may and may not do. A mock would test my idea of Postgres, not Postgres.
2. The tests only run against a Postgres on this machine, and never use the database named in the URL:
   they create two scratch databases beside it and drop them at the end. Before any table is emptied,
   the fixture checks that the project's own `get_conn()` really landed on the scratch one.
3. OpenAQ stays fake in the database tests (prepared answers instead of downloads), so no test needs
   the internet or the API key.
4. Without `TEST_DATABASE_URL` the 25 database tests are skipped, so plain `pytest` works with Docker
   off. CI must never skip them silently, and the coverage floor guards that: it is now 55%, between
   46.88% (without the database tests) and 60.19% (with them).
5. The same image (`postgres:16-alpine`) and the same address locally and in CI, so one command line
   works in both places. In CI it is a service container: an empty Postgres that lives for one job.

**Numbers** (laptop, Python 3.14.7). With the database: 132 passed, coverage 60.19% (1,090 of 1,811
statements), up from 36.43% (659 of 1,809). Without it: 107 passed, 25 skipped, 46.88% (849 of 1,811).
By file: `db.py` 20 → 92, `ingest.py` 0 → 99, `openaq_client.py` 0 → 100, `forecast.py` 55 → 99,
`service.py` 56 → 96, `make_readonly_role.py` 0 → 71, `seed_local.py` 0 → 69, `bench.py` 0 → 46.
CI: three green on de2ec40 (Python 3.12, Python 3.14, image).

**What the tests found.**

- A bug in `bench.py`. "p95" over the default 30 requests was the 28th value of 30, which is the 93rd
  percentile: the rank was `round(28.5)`, and Python rounds that to 28. It now rounds up (the 29th).
  Every p95 measured before today with 30 requests is therefore slightly too low. The latency numbers
  get measured again before they are used anywhere.
- Nothing wrong in the SQL. The `/stats` query was checked against a case worked out by hand (three
  scored forecasts: MAE 10.0, bias -6.67, coverage 0.667, persistence MAE 8.33; readings of 0 and 990
  left out by the value policy) and it matched.
- `forecast.py` end to end, on made-up readings. Ten days of hourly readings with the newest 3 h old
  give 21 forecasts, all `full`; a second run adds 0; one more reading adds 1. With two 5-hour holes:
  12 `full`, 4 `day`, 5 `short`, and no origin hour without a forecast.

**Known gaps, written down and not fixed today.**

- `healthcheck.py` is at 12%. Its rule is the one `service.health()` uses, and that is tested; the
  script itself is not.
- `run_ingest` only catches `OpenAQError`. Any other exception ends the run with its row still saying
  `running`. To fix, with a test first.
- The ingest tests replace `flatten_hours` with a fake. It has its own tests, but no test yet takes a
  real API answer all the way into the table.
- One-off scripts stay untested on purpose: `explore_api.py`, `audit_sensors.py`, `backfill.py`,
  `quality_report.py`, `apply_schema.py`, `runsql.py`.

## 2026-11-19 — the band stays: sizing it from recent errors does not earn a switch

**The worry.** Live, the full tier of v2 has 125 scored hours and 65.6% of the actuals fell inside a
band meant to hold 80% (`results/live_2026-11-19.txt`). The band is sized once, from the relative
errors of the last 8 weeks before the model was fitted, and never changes. Two suspects: eight weeks
reaches too far back, or "once" is the problem and the band should learn from its own recent misses.

**The experiment** (`band_calibration.py`, results in `results/band_calibration.csv`). The same ridge,
the same six folds and the same rows as Step 9, with the band sized eight ways: once, from the last
8, 4 or 2 weeks; or re-sized for every forecast from the errors of the last 56, 28, 14, 7 or 3 days.
An error is used only once it is known, 24 hours after its forecast; the tests pin that to the hour.
The script's 8-week band equals the live recipe exactly (largest difference 0.00e+00). The rule for
switching was written at the top of the script before it was run on the real data.

| Scheme | Mean coverage | Worst fold | fold_miss | Width | Interval score |
|---|---|---|---|---|---|
| static_8w (live) | 0.814 | 0.721 | 0.049 | 31.4 | 45.01 |
| static_4w | 0.759 | 0.670 | 0.058 | 26.0 | 43.80 |
| static_2w | 0.722 | 0.531 | 0.101 | 24.6 | 46.64 |
| rolling_56d | 0.798 | 0.743 | 0.040 | 29.1 | 43.88 |
| rolling_28d | 0.777 | 0.720 | 0.040 | 28.2 | 43.97 |
| rolling_14d | 0.765 | 0.718 | 0.035 | 28.4 | 44.60 |
| rolling_7d | 0.751 | 0.727 | 0.049 | 28.9 | 47.13 |
| rolling_3d | 0.721 | 0.637 | 0.079 | 28.2 | 49.90 |

Data: 10,225 usable rows through 11 Nov 2026 (the feature file written on 13 Nov, when v2 was fitted).
Test windows: 11 Dec 2025 to 11 Nov 2026.

**What it says.**

1. A shorter look-back is worse, not better. Sized once from 2 weeks, one fold drops to 0.531.
2. The shorter the memory of a rolling band, the lower its coverage: 0.798, 0.777, 0.765, 0.751, 0.721.
   With 7 days it is under 0.80 in all six folds. Errors come in runs of days; a short window has
   seen only the current kind of day, and the next kind falls outside.
3. Re-sizing with the same 8-week memory (rolling_56d) helps a little: fold_miss 0.040 against 0.049,
   a band 7% narrower, interval score 43.88 against 45.01. That is real but small.
4. Shifting the point forecast to the middle of its band does not help. Mean MAE over the folds: plain
   ridge 8.91, shifted 8.93 at best (rolling_56d) and 9.99 at worst (rolling_3d). Persistence: 9.61.

**Decision: the band stays as it is.** The rule asked for a fold_miss at least 0.02 lower than the
live band's. The largest gain is 0.014 (rolling_14d), and that scheme holds only 0.765 on average.
The expectation was that a rolling band would win. It does not, and a band that re-sizes itself is
one more moving part that has not earned its place.

**Where the live band misses** (`sql/12_band.sql`, Q46 to Q48).

- On both sides: of 125 actuals, 19 fell below the band and 24 above. The band's edges are -0.253 and
  +0.416 of the forecast; the live errors' 10th and 90th percentile are -0.290 and +0.557, with the
  middle at +0.116. So this week's errors are wider than the band and lean high.
- On a few days: 13, 14 and 15 Nov hold 31 of v2's 44 misses. The daily mean went 71.6, 78.1, 54.0:
  two days the level ran 15 to 20 above the forecast, then one day 20 below it. Persistence was about
  as far off on those days (MAE 17.4, 19.9, 26.3 against the model's 20.2, 20.7, 20.7): no forecast
  built on the day before saw these swings coming. On 16, 17 and 19 Nov coverage was 0.83, 0.92 and
  0.89. On 18 Nov the level jumped again (89.7 against a forecast of 66.2) and coverage was 0.74.

**Also seen, and to be said plainly in the write-up.**

- In the winter fold (11 Dec to 3 Feb) the ridge does not beat persistence: MAE 16.27 against 15.98.
  In the other five folds it does (9.76 / 10.70, 8.57 / 9.84, 4.73 / 5.21, 4.47 / 5.29, 9.66 / 10.66).
  The live tie (18.60 against 18.54) is at winter-like levels, so it matches the record rather than
  contradicting it. The yearly average hides this.
- Six 8-week test windows cover 48 weeks. 12 Nov to 10 Dec has never been a test window, and that is
  where the live record is now.

**Still open.** The band holds 0.81 over 48 weeks, but nothing yet says how far a single week can
stray from that. Next: week-by-week coverage inside the walk-forward folds, so that the live number
on the 29 Nov checkpoint is judged against that spread and not against 0.80 alone.

## 2026-11-20 — one week at a time: a yardstick for the live number

**The question.** Step 15 kept the band: over the 48 test weeks it holds 0.81 of the actuals. Live it
held 0.656 after its first week (19 Nov). A figure for a whole year cannot say whether one week at
0.66 is a band gone wrong or an ordinary bad week. So: how far did single weeks stray in the record?

**What was done** (`band_weekly.py`, `results/band_weekly.csv`, `figures/band_weekly.png`). Every
walk-forward test row is scored with the band exactly as it is live, then each 8-week test window is
cut into single weeks and into fortnights, and each block is scored alone. A block counts only if at
least half of its hours have a scored forecast. Self-check: the six fold coverages come out as in
Step 15 (0.823, 0.775, 0.721, 0.847, 0.871, 0.847), and all 5,532 test rows sit in exactly one block.

| Block | Counted | Left out | Lowest | 10th pct | Median | 90th pct | Highest | Under 0.70 | Under 0.65 |
|---|---|---|---|---|---|---|---|---|---|
| One week | 36 | 12 | 0.60 | 0.67 | 0.83 | 0.94 | 0.97 | 5 | 3 |
| Two weeks | 19 | 5 | 0.64 | 0.73 | 0.80 | 0.92 | 0.94 | 1 | 1 |

**How to read the live number with it.**

- One week swings a lot. 5 of 36 test weeks were under 0.70, about one in seven. Three were lower than
  the live band's first week (0.656). A bad week, and not an unheard-of one.
- Two weeks swing much less. Only 1 of 19 fortnights was under 0.70, and the median is 0.80.
- So the checkpoint line was put in a sensible place. On 29 Nov the full tier will have about 16 days
  of record. Under 0.70 then would be worse than 18 of 19 fortnights in the record: unusual, and to be
  reported as such. At or above 0.70 is inside what the record shows.
- The number judged on 29 Nov is the coverage of v2's full tier, the one that was flagged. Today it is
  0.677 on 158 scored hours (all of v2 together: 124 of 176, 0.705).

**The same yardstick for accuracy.** The ridge had the lower MAE in 33 of 36 test weeks and 16 of 19
fortnights. All three losing weeks are in the winter fold (11 Dec to 3 Feb; ridge MAE / persistence
MAE of 1.12, 1.17 and 1.06), which fits what Step 15 showed for that fold. Of the three losing
fortnights two are in the winter fold (1.03, 1.02) and one is in the monsoon fold (1.21; it contains
a thin week).

**Live today** (`results/live_2026-11-20.txt`). Full tier of v2, 158 scored hours: MAE 17.58 against
18.34 for persistence (4% lower; it was a tie until now); bias -2.18; coverage 0.677. Day by day since
16 Nov the band held 0.83, 0.92, 0.74, 0.75 and 0.83. Availability: 168 of 168 hours again.

**What the yardstick does not cover.**

- 12 of the 48 test weeks are left out because fewer than half of their hours have a full-tier
  forecast. Six of them are in January and February 2026 (8 to 28 Jan, 5 to 25 Feb) and three are the
  last three weeks before v2 was fitted (22 Oct to 11 Nov). So the yardstick has less winter in it
  than the calendar has.
- 12 Nov to 10 Dec has never been a test window, and that is where the live record is.

**Decision.** Nothing changes in what is served. The 29 Nov checkpoint stands as written, now with
something to judge the number against.

## 2026-11-21 — one data file, every number

**Why.** The walk-forward folds are counted back from the newest row, so every time the feature file
grew, every number moved a little (ridge against persistence was 8.66 vs 9.36 on 3 Nov and is 8.91 vs
9.61 now). The result files had been written on different days: five of them on 3 to 7 Nov from older
data, the rest since 13 Nov. A write-up that quotes them side by side would be mixing data sets.

**What was done.** The feature file of 13 Nov, the one v2 was fitted on, is frozen, and all eight
evaluation scripts were run on it in one go.

- The file: 10,225 usable rows through 11 Nov 2026 23:30 UTC. Its SHA-256 fingerprint is
  `4511c99e0868bc1e81e196d90ebbfc5e0035c6036fa2013d90b03002ef691f64`. A copy is kept as
  `data/features_12238693_frozen_2026-11-11.csv`. The `data/` folder is not in git; the fingerprint is.
- The run: `results/frozen_run_2026-11-11.txt` holds the whole output, with the fingerprint on top.
- The proof that it is one file: after the run git showed the five old result files and their figures
  as changed, and the `tier_` and `band_` files as unchanged. Those were regenerated byte for byte.

**The numbers for the write-up.** Test design: six 8-week windows, 11 Dec 2025 to 11 Nov 2026,
5,532 scored hours for the full model.

| What | Number | File in `results/` |
|---|---|---|
| Ridge against persistence, mean of the six folds | MAE 8.91 against 9.61, 7.3% lower | `model_comparison.csv` |
| The same, all scored hours together | 8.60 against 9.31, 7.6% lower | `error_analysis.csv` |
| Folds the ridge wins | 5 of 6; not the winter fold (16.27 against 15.98) | `model_comparison.csv` |
| Gradient boosting, five variants | 9.73 to 10.72, all worse than persistence; up to 21.85 in the winter fold | `model_comparison.csv` |
| Slices where persistence wins | 3 of 26: the winter fold, January 2026, hours above 90 | `error_analysis.csv` |
| Hours above 90 µg/m³ (253 of 5,532) | ridge 27.47 against 22.99 | `error_analysis.csv` |
| 80% band that scales with the forecast | coverage 0.814, worst fold 0.721, width 31.4 | `intervals.csv` |
| Fixed-width band | 0.791 on average, but 0.522 to 0.964 across folds | `intervals.csv` |
| Quantile regression band | 0.701 | `intervals.csv` |
| The chosen band in hours above 90 | 0.463 | `intervals.csv` |
| Hours with a forecast: full, +day, +short tier | 73.3%, 85.5%, 90.6% of all hours | `tier_availability.csv` |
| All tiers together against the full tier alone | MAE 8.592 on 6,822 hours against 8.601 on 5,532 | `tier_comparison.csv` |
| Band sized eight ways | the live one stays; the best other gains 0.014, the rule asks 0.02 | `band_calibration.csv` |
| One week at a time | under 0.70 in 5 of 36 weeks and in 1 of 19 fortnights | `band_weekly.csv` |

**Limits the write-up has to state, each with its number above.**

- Winter. The ridge does not beat persistence in the winter fold, and loses in January.
- Bad-air hours. Above 90 µg/m³ the ridge is worse than persistence, and the 80% band holds only 46%
  of the actuals. Those are 253 hours, 4.6% of the record, and they are the hours people care about most.
- 12 Nov to 10 Dec has never been a test window.

**Rules from here.**

- `python dataset.py` is not run again until the write-up is finished. If it is, the frozen file comes
  back with `cp data/features_12238693_frozen_2026-11-11.csv data/features_12238693.csv`, and
  `shasum -a 256` must print the fingerprint above.
- README and resume take their numbers from this run. Dated notes and earlier entries keep theirs:
  they were true for the data of their day.
- 151 automated tests as of today (126 without a database, 25 against Postgres).

## 2026-11-22 — a new README, and a forecast picture that does not flatter

**The README** was still the "in progress" page of 30 Oct. It is rewritten: what the project is, how
it works, the results of the frozen run (each number linked to its result file), where the model
loses, the live record with its date, how to run it. Every link in it is checked against git.

**The old forecast picture was wrong in three ways** (`figures/intervals.png`, from `intervals.py`,
7 Nov). Seen only when the README showed it on GitHub:

- Its title said "last 14 days", but it drew the last 336 scored hours, and with the holes in the
  data those run from early October to mid-November: five weeks.
- It joined the points on both sides of a hole with a straight line, so a week without data looked
  like a week with a flat forecast.
- It drew each forecast at the hour it was made, not the hour it was for. Everything was a day off.

**What replaces it in the README** (`readme_figures.py`, tested in `tests/test_readme_figures.py`):

- `figures/forecast_example.png`: an ordinary fortnight chosen by a rule, the most recent 14 days of
  the test windows with at least 80% of the hours present. That is 22 Sep to 6 Oct 2026: 272 of 336
  hours, MAE 7.51 against 8.21 for persistence, 77% of the actuals inside the band.
- `figures/forecast_diwali.png`: 5 to 11 Nov 2026. Highest reading 285 µg/m³ on Mon 9 Nov at 09:00 IST;
  the forecast for that hour was 77, band up to 113. Only 62 of the 168 hours have a forecast and a
  reading. It is in the README under "Where it loses".

Both draw a forecast at the hour it is for, and break the line at every missing hour.

**Left as it is for now.** `figures/intervals.png` and the function that draws it. The README no longer
shows it. To fix when `intervals.py` is next run.

157 automated tests as of today (132 without a database, 25 against Postgres).
