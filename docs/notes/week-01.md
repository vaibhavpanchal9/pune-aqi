# Week 1 review — Sunday 1 November 2026

## What shipped (26–30 Oct)
- Restart: Docker/local Postgres blocked by a system Postgres on port 5432; moved to Neon instead.
- Step 1: Neon project (Singapore); `db.py` prefers `DATABASE_URL`; `apply_schema.py` created the tables.
- Step 2: GitHub Actions `ingest.yml` (now hourly cron, 72 h lookback, two secrets); first unattended run
  26 Oct 2026 — the resume clock. `healthcheck.py` redesigned: red only if our last good run > 12 h,
  upstream lag (> 9 h) is a yellow warning.
- Step 3: `backfill.py` (month by month, commit per month, skip rule on the worst sensor): 21 months,
  145,796 rows, 8.5 min. `runsql.py`. Inventory → `docs/data_inventory.md`; primary station confirmed
  (Pashan 12238693, best coverage).
- Step 4a: `sql/01–06` — basics, GROUP BY, JOIN/LEFT JOIN, CASE, coverage with generate_series, three
  exercises. Found: two seasons (Dec 70.1 vs May 16.4), daily shape (10 am peak, 4 pm trough), Hadapsar
  dead Jun–Sep 2025, network-wide outages Apr 2025 / Jan 2026 / Jun 2026 / Oct 2026.
- Step 4b: `sql/07–09` — window functions (longest gaps; 24 rows ≠ 24 hours: 80.4 vs 88.5 on 4 Feb),
  EXPLAIN (Seq Scan 183 ms vs index 2.4 ms; `max()` 0.03 ms), `v_features` view on the hourly grid,
  tested: lag_24 correct on 13,452 / 13,452 rows. Two redundant indexes dropped.
- Step 5: `quality_report.py` (gaps, impossible values, stuck runs, alignment, outage days) →
  `docs/data_quality.md`, `results/quality_report_2026-10-30.txt`; value policy and 3-hour gap policy
  in `decisions.md`.
- Admin (done Friday): `docs/runbook.md`, README status, `docs/resume_admin.md`; `docs/Pune-AQI-Explained.html`.
- Database today: 147,239 readings, 13 stations, 5 days of unattended collection.

## What didn't
- GitHub delivers ~4 of 24 hourly slots; newest reading is often 6–10 h old. Fix planned for Week 2:
  an external timer (cron-job.org) triggering the workflow through GitHub's API.
- resume_admin.md: certificate names/URLs and the Agri-Route title — (filled / still TODO: say which).
- Weekly meter photographs: not started; Book 3 is after 6 December, so this is not a miss.

## What I couldn't explain if asked
(Yours. Read chapter 13 of the explainer aloud and write down where you stalled — one line each.
Candidates: why the primary key makes reruns safe · why features are built on a grid · what a LEFT JOIN
does that a JOIN doesn't · why `max(measured_at)` costs 0.03 ms · what "best-effort scheduling" means ·
why zeros are removed but not edited.)
-
-
-

## Monday's row — Step 6 (1/2), 2 Nov
healthcheck, paste. Read 4.4. `dataset.py`: load `v_features` for Pashan (or build the grid in pandas),
apply the value policy, apply the 3-hour forward fill, align the 24 h target; `tests/test_target.py`
proves the target is 24 hours ahead of its features. Done when `python dataset.py` prints a shape around
(10,900, 25) and pytest is green.