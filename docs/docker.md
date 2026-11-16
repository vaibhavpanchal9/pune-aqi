# Running in Docker

## What the image is

- `python:3.12-slim`, the four libraries in `requirements-api.txt`, five Python files (`app.py`,
  `service.py`, `modelfile.py`, `db.py`, `healthcheck.py`) and `models/`. About 250 MB on disk,
  55 MB compressed.
- No pandas and no scikit-learn: the model is numbers in JSON and the forecasts are in the database.
- No secrets: `.env` is excluded by `.dockerignore`; `DATABASE_URL` arrives as an environment variable
  when the container starts.
- Runs as a non-root user (`app`).
- The API tests run inside the image during the build (the `test` stage). The final image copies a
  marker file from that stage, so a failing test means no image.
- The container health check asks `/` (a static answer), not `/health` (which queries the database),
  so a sleeping free-tier database is not woken every 30 seconds. Use `/` as the health path on any host.

## Commands

```bash
docker compose build api                              # build (runs the API tests on the way)
docker build --target test -t pune-aqi-api:test . \
  && docker run --rm pune-aqi-api:test python -m pytest tests/test_api.py -q
docker compose --profile cloud up -d api-cloud        # port 8001, the image talking to Neon (.env)
docker compose up -d db api                           # port 8000, with a local Postgres on host port 5433
python seed_local.py                                  # copy 30 days from Neon into the local Postgres
docker compose --profile cloud down                   # stop everything; the local data is kept
docker compose down -v                                # stop and delete the local data too
```

Ports are bound to 127.0.0.1. The local database password in `docker-compose.yml` is for the throwaway
container only; it is not a secret and is never used anywhere else.

## Pointing the pipeline at the local database

```bash
DATABASE_URL=postgresql://aqi:localdev@127.0.0.1:5433/aqi python forecast.py --dry-run
```

A variable set on the command line wins over `.env`.

## First run, 16 Nov 2026

Build 20.7 s; 8 tests passed in 0.36 s inside the container; `/health` answered `ok` from both the cloud
profile and the local stack. Seed: 19 locations, 215 sensors, 7,169 readings, 298 runs, 160 forecasts.
