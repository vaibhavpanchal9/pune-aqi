# Runbook — pune-aqi

## The system in one paragraph
A GitHub Actions job (`.github/workflows/ingest.yml`, cron `23 * * * *` UTC) runs `ingest.py --hours-back 72`
against OpenAQ v3 and writes to a Neon Postgres (project `pune-aqi`, Singapore). `healthcheck.py` runs
as the job's last step and exits 1 only if OUR last successful run is older than STALE_HOURS (12);
upstream lag (newest reading older than UPSTREAM_HOURS, 9) is a yellow warning, exit 0. Local work
uses the same database through `DATABASE_URL` in `.env`. Nothing depends on the laptop being awake.

## Every day
    python healthcheck.py          # 10 s. Read: runs in last 24h, last run, STATUS.

## Reading the healthcheck
- `STATUS: OK` — nothing to do.
- `OK … UPSTREAM LAG` — our job runs; CPCB/OpenAQ is behind. Nothing to fix. If it lasts > 24 h,
  add the dates to docs/data_quality.md section F.
- `STATUS: BROKEN` — no successful run for 12 h. Go to github.com/vaibhavpanchal9/pune-aqi/actions:
  1. No runs at all in the last 12 h → the schedule stalled. Click `ingest` → Run workflow. If it goes
     green, GitHub skipped slots; if the schedule stays dead for a day, push any commit touching
     `.github/workflows/ingest.yml` (re-registers the cron).
  2. Red runs → open the newest, open the red step, read the last 15 lines.
     - `password authentication failed` / `could not connect` → DATABASE_URL secret is wrong or the
       Neon password was reset. Fix the secret under Settings → Secrets and variables → Actions.
     - `401` / `403` from OpenAQ → OPENAQ_KEY secret invalid or rate-limited. Check the key at
       explore.openaq.org → account; 429s clear by themselves within the hour.
     - `500` from OpenAQ three times → their outage; the next run retries. Nothing to do.
     - A Python traceback → a bug. Reproduce locally with the same command, fix, commit, push, Run workflow.

## Where the logs are
- Cloud: Actions tab → run → `ingest last 72 h` step. GitHub keeps logs 90 days.
- Local: `logs/ingest.log` (gitignored) — every local run of ingest.py/backfill.py appends to it.
- Database: `SELECT run_at, mode, status, rows_inserted, error_text FROM ingestion_runs ORDER BY run_at DESC LIMIT 20;`
  (`python runsql.py -c "..."`). This table is the resume evidence; never delete from it.

## Switching the database
- Neon (default): `DATABASE_URL=postgresql://…` present in `.env`. All scripts use it.
- Local Docker Postgres: comment out the DATABASE_URL line in `.env`; scripts fall back to PGHOST/PGPORT/...
  Note: port 5432 on this Mac is held by a system Postgres (PID 535, user postgres, since Oct 2026);
  the container `aqi-pg` cannot bind it. Re-create it on 5433 when needed:
  `docker rm -f aqi-pg && docker run --name aqi-pg -e POSTGRES_PASSWORD=… -e POSTGRES_DB=aqi -p 5433:5432 -d --restart unless-stopped postgres:16`
  then set `PGPORT=5433` in `.env` and run `python apply_schema.py`.

## Rebuilding from nothing
    python apply_schema.py            # tables, indexes, v_features (all IF NOT EXISTS / OR REPLACE)
    python ingest.py --discover       # station registry (19 locations, 13 live PM2.5 sensors)
    python backfill.py                # Feb 2025 -> today, month by month, skips full months
    python healthcheck.py

## Secrets
Live in three places only: `.env` (gitignored), GitHub Actions secrets, later Render env vars.
Never in code, never in chat, never in a commit. If one leaks: rotate first (Neon: Branches → Roles &
Databases → Reset password; OpenAQ: account page), then update the three places, then worry about how.

## Known upstream behaviour
- OpenAQ Pune feed stops occasionally for days (23–27 Oct 2026; 11–19 Jan 2026; 9–10 Apr 2025).
  The 72-hour lookback refetches the gap automatically when it comes back.
- CPCB hours are IST hours, stored as UTC :30. Convert only for display.
- Zeros and long flat runs are stuck instruments, not air (docs/data_quality.md).
## Hourly trigger (added 8 Nov 2026)

GitHub's own `schedule:` cron is best-effort: between 26 Oct and 7 Nov it delivered 47 runs
in 12 days, about 4 per day (sql/10_gate1_evidence.sql). Since 8 Nov the hourly run is
dispatched from outside GitHub:

- cron-job.org job "pune-aqi ingest": every hour at :00 UTC, POST to
  https://api.github.com/repos/vaibhavpanchal9/pune-aqi/actions/workflows/ingest.yml/dispatches
  with body {"ref":"main"}.
- Auth: fine-grained personal access token "cron-job dispatch" -- this repo only, Actions
  read/write only (GitHub confirmed `x-accepted-github-permissions: actions=write` on the test
  call). Expires 8 Nov 2027 IST. The token lives only inside cron-job.org: not in .env, not in
  Actions secrets, not in this repo.
- The GitHub cron `23 * * * *` stays in ingest.yml as a fallback. Two runs in the same hour
  are harmless: inserts are ON CONFLICT DO NOTHING.
- If runs stop: cron-job.org -> job history shows the HTTP status of each call.
  401 = token expired or revoked (regenerate on GitHub, paste into the job's Authorization
  header). 404 = token lost Actions write, or the workflow file was renamed.
- The header X-GitHub-Api-Version: 2022-11-28 is marked deprecated by GitHub with a sunset
  of 10 Mar 2028. Before then, change it to a newer version.

## The forecast step (added 9 Nov 2026)

After `ingest.py`, the workflow runs `python forecast.py`: it loads `models/v1.json` and the last 14 days
of readings for sensor 12238693, builds the same features as training (dataset.py), and inserts a forecast
for every origin hour of the last 24 h that is complete and not yet on file. The step prints how many rows
it wrote and the newest forecast; "0 new rows" is normal when no new reading has arrived.
`python forecast.py --dry-run` shows what it would write without writing. The forecast and healthcheck
steps run even if ingest failed.

Evidence: `python runsql.py sql/11_forecasts.sql` -- Q41 what is on file, Q42 lead time, Q43 live MAE,
coverage and persistence on the same hours, Q44 availability.

Refit (a new version): `python dataset.py && python fit_model.py --version v2`, commit `models/v2.json`,
change `DEFAULT_MODEL` in forecast.py (or pass `--model`). Old rows keep their `model_version`.

## Model versions and tiers (added 13 Nov 2026)

The hourly job reads the model named in modelfile.py (DEFAULT_MODEL, now models/v2.json). This replaces
the older note about DEFAULT_MODEL in forecast.py. v2 has three tiers (full > day > short); the log line
"origin hours: N in the last 24 h -> full a, day b, short c, no tier d" says which tier served how many
hours. "no tier" hours are the first 3 after a gap, or hours with no reading.

A new version: `python dataset.py && python tiers.py && python fit_model.py --version v3`, then change
DEFAULT_MODEL in modelfile.py and commit both. fit_model.py refuses to overwrite an existing model file:
a version name means one model forever, because rows in `forecasts` refer to it.

## If the laptop cannot reach the database (13 Nov 2026)

`could not translate host name ... neon.tech` is the laptop's DNS, not Neon and not the pipeline (the
cloud job kept running). Check: `nslookup <host> 8.8.8.8` answers while plain `nslookup <host>` says
REFUSED. Fix: `sudo networksetup -setdnsservers Wi-Fi 1.1.1.1 8.8.8.8` (undo with `... Wi-Fi empty`).
