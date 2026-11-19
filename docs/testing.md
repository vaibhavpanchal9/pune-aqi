# Tests

132 automated tests (19 Nov 2026). 107 need nothing but Python. 25 need a Postgres, and get a real one.

## Running them

Everything that needs no database (the 25 database tests are skipped):

```bash
python -m pytest -q
```

Everything, with Docker Desktop running:

```bash
docker compose up -d --wait db
TEST_DATABASE_URL=postgresql://aqi:localdev@127.0.0.1:5433/aqi python -m pytest -q --cov=. --cov-report=term
docker compose down
```

How many tests each file holds:

```bash
python -m pytest --collect-only -q | grep "::" | cut -d: -f1 | sort | uniq -c
```

## What is tested where

| File | What it pins down | Needs |
|---|---|---|
| `tests/test_db_integration.py` | The real SQL: `schema.sql`, readings saved once, an ingest run and its row in `ingestion_runs`, `forecast.py` end to end, the queries behind `/forecast`, `/stats` and `/health`, the local copy, the read-only role | A local Postgres |
| `tests/test_openaq_client.py` | What the OpenAQ client retries, what it never retries, how long it waits, paging | Nothing (fake internet, fake sleep) |
| `tests/test_api.py` | Status codes and response shapes of the API | Nothing (fake queries) |
| `tests/test_transform.py` | Turning OpenAQ's JSON into rows | Nothing (saved answers in `tests/fixtures/`) |
| `tests/test_local_tools.py` | `.env` is changed one line at a time; the copy script only writes to this machine; which request "p95" is | Nothing |
| the other test files | Features and target, splits, metrics, training, evaluation, error analysis, the band, tiers, the forecast table | Nothing |

## The database tests

Real: Postgres 16, `schema.sql`, and every query in `db.py`, `ingest.py`, `dataset.py`, `forecast.py`, `service.py`, `seed_local.py` and `make_readonly_role.py`.

Fake: OpenAQ. The download functions are replaced by prepared answers, so no test needs the internet or the API key.

These tests create and drop databases, so three rules keep real data safe:

1. The server must be on this machine (`127.0.0.1` or `localhost`). Anything else and nothing runs.
2. They never use the database named in `TEST_DATABASE_URL`. They make two scratch databases beside it, apply `schema.sql` to them, and drop them at the end. The seeded local database is left alone.
3. Before a table is emptied, the fixture checks that the project's own `get_conn()` landed on the scratch database.

## In CI

`.github/workflows/ci.yml` starts an empty `postgres:16-alpine` next to the tests (a service container), at the same address as the local one. The tests run on Python 3.12 and 3.14.

Coverage, measured on 19 Nov 2026 with Python 3.14: 60.19% with the database tests, 46.88% without them. The floor in CI is 55%. So if the database tests were ever skipped by mistake, the job fails instead of passing quietly.

## Not tested, and why

- One-off scripts that were run by hand and print for a person: `explore_api.py`, `audit_sensors.py`, `backfill.py`, `quality_report.py`, `apply_schema.py`, `runsql.py`.
- The `main()` of the training and evaluation scripts. Their functions are tested; the printing is not.
- `healthcheck.py` itself. Its rule is the one `service.health()` uses, and that one is tested. A test for the script is still owed.
