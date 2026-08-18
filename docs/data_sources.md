# Data sources

## OpenAQ (primary)

- Base URL: `https://api.openaq.org/v3`
- Docs: https://docs.openaq.org
- Auth: header `X-API-Key`
- Key from: https://explore.openaq.org
- v1 and v2 were retired 31 Jan 2025 and return HTTP 410. Ignore any
  tutorial using `/v2/measurements`.

### Query shape used here

- `GET /v3/locations?coordinates=18.5204,73.8567&radius=25000&parameters_id=2`
- `coordinates` is **latitude,longitude** (Y,X). Swapping them does not error.
- `radius` is metres, max 25000.
- `parameters_id=2` is PM2.5.
- `GET /v3/sensors/{id}/hours?datetime_from=...&datetime_to=...` for the data.

### Rate limit

FILL THIS IN — Day 3, task 10. Read https://docs.openaq.org/using-the-api/rate-limits
and write the exact number of requests allowed here, plus the sleep you set in
`openaq_client.SLEEP_BETWEEN_CALLS`.

### Stations near Pune

FILL THIS IN — Day 1, task 6. Run `python explore_api.py --markdown` and paste
the table below.

| ID | Station | Provider | Reference monitor | Parameters | First data | Last data | Days stale |
|---|---|---|---|---|---|---|---|

Then answer, one line each:

- How many stations report pm25?
- How many are reference-grade monitors vs low-cost sensors?
- Which station has the longest history?
- Which stations are dead (days stale > 30)?

## CPCB (secondary — Day 3)

FILL THIS IN — Day 3, task 5.
