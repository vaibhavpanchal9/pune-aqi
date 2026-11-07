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