# pune-aqi — Pune PM2.5 forecasting service (in progress)

Hourly PM2.5 from 13 reference-grade CPCB/MPCB/IITM stations around Pune, collected continuously
into a hosted Postgres by a scheduled job, with a 24-hour-ahead forecasting model and an API to follow.

**Status (30 Oct 2026):** data pipeline live since 26 Oct 2026 — GitHub Actions → OpenAQ v3 → Neon,
every hour, unattended. 146,000+ hourly readings back to Feb 2025. Feature table (`v_features`) built
on a regular hourly grid with a SQL correctness test. Quality audit and gap/value policies written.
Next: baselines, walk-forward evaluation, gradient boosting, intervals, FastAPI, Docker, Render.

## Layout
| file | does |
|---|---|
| `openaq_client.py` | OpenAQ v3 HTTP: locations, sensors, hourly pages, retries |
| `transform.py` | pure parsers from API JSON to rows (tested) |
| `db.py` | connection (DATABASE_URL first), inserts with ON CONFLICT DO NOTHING |
| `schema.sql` / `apply_schema.py` | tables, indexes, `v_features` view |
| `ingest.py` | `--discover`, live (`--hours-back`), backfill (`--from/--to`) |
| `backfill.py` | month-by-month backfill that skips months already full |
| `healthcheck.py` | our-job-broken (exit 1) vs upstream-lag (warning) |
| `quality_report.py` | gaps, impossible values, stuck sensors, outage days |
| `runsql.py` | run a .sql file or one query, print tables |
| `sql/` | the SQL written on this data, numbered |
| `docs/` | decisions, data_inventory, data_quality, sql_notes, runbook, notes/ |
| `.github/workflows/ingest.yml` | the scheduled job |

## Run it
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env            # fill OPENAQ_KEY and DATABASE_URL
    python apply_schema.py && python ingest.py --discover && python backfill.py
    python healthcheck.py

Data: OpenAQ (CC BY 4.0), original measurements by CPCB / MPCB / IITM.