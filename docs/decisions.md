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
