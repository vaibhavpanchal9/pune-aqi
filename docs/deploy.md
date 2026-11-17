# Deployment

**Live:** https://pune-aqi-api.onrender.com (interactive documentation at `/docs`)

## What runs where

| piece | where | started by |
|---|---|---|
| ingestion and forecasts | GitHub Actions (`.github/workflows/ingest.yml`) | cron-job.org, every hour |
| database | Neon Postgres, Singapore, free plan | always there; sleeps when idle |
| API | Render free web service, Singapore, Docker | `render.yaml` in this repository |

## The API on Render

- Built from the Dockerfile whenever a push changes a file that is inside the image (`buildFilter` in
  `render.yaml`). Docs and notes do not trigger a build. The API tests run inside the build.
- One setting lives only in Render's dashboard: `DATABASE_URL`, the read-only connection string.
- Health check path is `/` (a static answer), so the health check does not wake the database.
- Free plan: 0.1 CPU, 512 MB; sleeps after 15 minutes without traffic; the first request after that
  takes about a minute; 750 hours a month.

## The database user the API uses

`aqi_api`, made by `make_readonly_role.py`: SELECT on five tables, a 5 second statement timeout, at most
10 connections. Verified at creation on 18 Nov: it read 151,949 readings and a DELETE was refused.

To change its password: `python make_readonly_role.py --rotate`, then copy without displaying it
(`grep '^API_DATABASE_URL=' .env | cut -d= -f2- | tr -d '\n' | pbcopy`), paste into Render >
pune-aqi-api > Environment > DATABASE_URL, and save. Render redeploys with the new value.

## Latency, first measurement

`results/latency_2026-11-17.csv`: 17 Nov 18:59 UTC, from Pune, service awake, a new TLS connection per
request, 30 requests per endpoint.

| endpoint | first | p50 | p95 | max |
|---|---|---|---|---|
| `/` | 328 ms | 181 ms | 320 ms | 378 ms |
| `/health` | 173 ms | 177 ms | 259 ms | 349 ms |
| `/forecast` | 225 ms | 177 ms | 261 ms | 353 ms |
| `/stats` | 241 ms | 176 ms | 251 ms | 261 ms |

The API reuses an answer for 30 to 300 seconds, so p50 is mostly network time; "first" for `/forecast`
and `/stats` includes a database query. Waking from sleep is not in these numbers.
