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

## Latency

Two clocks. *End to end* is what a visitor waits: server plus network. *Server only* is the API's own
time, reported in the `Server-Timing` header on every answer; it does not depend on the visitor.
`python bench.py --url <address>` measures both.

| measured from Pune | end to end p50 | end to end p95 | server only |
|---|---|---|---|
| 17 Nov 18:59 UTC, good connection (`results/latency_2026-11-17.csv`) | 176-181 ms | 251-320 ms | not yet measured |
| 18 Nov 04:51 UTC, slow connection (`results/latency_cold_2026-11-18.csv`) | 1.8-2.5 s | 2.3-3.6 s | not yet measured |
| 18 Nov 15:48 UTC (`results/latency_2026-11-18.csv`) | 259-285 ms | 361-487 ms | about 1 ms from memory |

Server time for an answer that is not in memory (the first request after the cache expires):
`/forecast` 44 ms, `/stats` 81 ms, and `/health` 617 ms on a call that also had to wake the database.

On the slow connection a single round trip to the server took 1.4 s (`curl -w`: connect 1.4 s, TLS 2.8 s,
first byte 4.1 s), so 2 seconds per request was three round trips of network and no server time at all.
That measurement is why the header exists.

**Cold start.** The free host sleeps after 15 minutes without traffic. The first request then took
25 s, 18 s and 14 s on three occasions on 18 Nov. Open the address a minute before a demo.

## The live page on GitHub Pages (28 Nov 2026)

https://vaibhavpanchal9.github.io/pune-aqi/ is the file `docs/index.html`. GitHub Pages serves the `docs/`
folder of the `main` branch (repository Settings > Pages > Deploy from a branch > `main`, `/docs`).

- **Nothing is built.** The empty file `docs/.nojekyll` tells GitHub to serve the folder as it is. A push
  that changes `docs/` is live a minute or two later ("pages build and deployment" under Actions).
- **The page has no server.** The reader's browser asks the API on Render directly. That is why the API
  allows other sites to read it ([api.md](api.md)).
- **Page and API are apart on purpose.** The API sleeps when nobody uses it and can take up to a minute
  to wake. The page is there at once, and says that the service is waking.
- **Everything in `docs/` has a web address now.** These documents were public on GitHub already.
- **Render ignores the page.** `docs/` is not in the build filter of `render.yaml`, so a change to the
  page does not rebuild the API.
