# The API

Three read-only endpoints over the `forecasts` table, served by FastAPI (`app.py`, queries in
`service.py`). Interactive documentation is generated from the code at `/docs`.

Run it locally:

```bash
uvicorn app:app --reload          # http://127.0.0.1:8000/docs
pytest tests/test_api.py -v       # 8 tests, no database needed
python service.py                 # the three responses as JSON, straight from the database
```

Times are UTC in ISO 8601 (`...Z`); `/forecast` adds a human-readable IST label per row.

## GET /health

Is the pipeline alive. Always 200; read `status`:

| status | meaning | rule (same as healthcheck.py) |
|---|---|---|
| `ok` | our job runs and data is fresh | last ok run < 12 h ago and newest reading < 6 h old |
| `upstream_lag` | our job runs; OpenAQ/CPCB is behind | newest reading ≥ 6 h old |
| `broken` | our job has not run | last ok run ≥ 12 h ago |

Sections: `pipeline` (last ok run, runs in the last 24 h), `data` (newest reading of the served
sensor), `forecasts` (hours ahead on file, newest target, last issued).

## GET /forecast?sensor_id=12238693

The forecasts on file for hours still ahead, oldest target first. One row per target hour, each
made 24 h before its target by the v1 ridge model, with the 80% residual-ratio band.

| code | when |
|---|---|
| 200 | the served sensor; `forecasts` may be an empty list when nothing is ahead (upstream outage) |
| 404 | a sensor id with no model (only the modelled station is served) |
| 422 | `sensor_id` is not an integer |

Fields per row: `target_time`, `target_time_ist`, `lead_hours` (from now), `point`, `lower`,
`upper` (µg/m³), `issued_at`. Top level: `station`, `model_version`, `horizon_hours`, `band`,
`data_as_of` (the newest reading hour the forecasts used), `generated_at`.

Example row, from the first batch issued on 9 Nov 2026 at 10:17 IST (the Diwali-night forecast):

```json
{
  "target_time": "2026-11-09T17:30:00Z",
  "target_time_ist": "Mon 09 Nov 23:00 IST",
  "lead_hours": 12.7,
  "point": 138.4,
  "lower": 100.3,
  "upper": 193.9,
  "issued_at": "2026-11-09T04:47:12Z"
}
```

Why `lead_hours` is less than 24: readings reach OpenAQ 3–11 h after the hour, so a forecast made
"24 h ahead of its origin hour" is issued later than that. The lead time you actually get is
24 h minus the upstream lag; `/stats` reports the mean.

## GET /stats

The live record next to the figure the model was chosen on:

- `live` — forecasts whose target hour now has a reading, scored as they were issued (never
  revised): `scored_hours`, `mae`, `bias`, `coverage_80`, `mean_width`, and `persistence_mae` on the
  same hours. Grows by about one hour per hour.
- `lead_time` — mean issue delay and mean / minimum lead.
- `availability_7d` — how many of the last 168 hours had a forecast on file (none when a feature
  was missing at issue time).
- `walk_forward` — the Step 8 result from `results/model_comparison.csv`, read out of the model
  file: ridge 8.657 vs persistence 9.357 µg/m³ over 6 folds.
- `trained_on` — rows and dates the live model was fitted on.

When `live.scored_hours` is small the live MAE is noise; the walk-forward number is the one to
quote until a few hundred hours have been scored.

## Design notes

- The served sensor, model version, horizon and band come from `models/v1.json`, so the API cannot
  disagree with what `forecast.py` writes.
- One database connection per request, closed after. Neon's free tier sleeps when idle, so the first
  request after a quiet spell can take about a second. A pool is a v2 item.
- Inputs and outputs are validated by Pydantic models; `/openapi.json` is generated from them.
- No writes, no authentication: everything served is already public data or derived from it.

## Changes with model v2 (13 Nov 2026)

- `/forecast`: every row has a `tier` field: `full`, `day` or `short`, the tier of the model that made it.
  The band is that tier's own 80% band.
- `/stats`: `live_by_tier` (the live record split by tier), `live_by_version` (v1's record stays visible
  next to v2's), `tiers` (each tier's features, the history it needs, and its out-of-sample figures), and
  `walk_forward` is now the cascade's figure from results/tier_comparison.csv: MAE 8.59 against 9.36 for
  persistence on 6,822 hours.
- The served model is the one named in modelfile.py, not a fixed v1 file.
