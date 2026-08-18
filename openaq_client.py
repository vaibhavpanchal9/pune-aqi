"""HTTP calls to the OpenAQ v3 API. Nothing else.

Key facts, all verified against docs.openaq.org on 17 Aug 2026:

  * Base URL is https://api.openaq.org/v3
  * v1 and v2 were switched off on 31 Jan 2025 and now return HTTP 410.
    Any tutorial you find using /v2/measurements is dead.
  * Auth is the header  X-API-Key: <key>   (not a query parameter,
    not a Bearer token)
  * coordinates is  latitude,longitude  -- Y then X. Reversing them does
    NOT error. It quietly returns stations somewhere else on Earth.
  * radius is metres, maximum 25000.
  * parameters_id=2 is PM2.5.
"""

import os
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.openaq.org/v3"
API_KEY = os.getenv("OPENAQ_KEY")

# Pune city centre. Change these if you'd rather centre on your campus.
PUNE_LAT = 18.5204
PUNE_LON = 73.8567
RADIUS_M = 25000          # the API's maximum

PM25_PARAMETER_ID = 2

TIMEOUT = 20              # seconds; without this, a hung request hangs the cron job forever
MAX_RETRIES = 3
SLEEP_BETWEEN_CALLS = 1.0  # be polite; raise this if you start seeing 429s

log = logging.getLogger(__name__)


class OpenAQError(RuntimeError):
    """Raised when the API says no in a way we can't recover from."""


def _headers():
    if not API_KEY:
        raise OpenAQError(
            "OPENAQ_KEY is not set. Put it in .env as OPENAQ_KEY=your-key-here. "
            "Get a key from https://explore.openaq.org"
        )
    return {"X-API-Key": API_KEY}


def _get(path, params=None):
    """One GET request, with retries and honest errors.

    Retries on network failures, 429 (rate limited) and 5xx (their problem).
    Does NOT retry on 401 or 422 — those mean your request is wrong, and
    sending it three more times will not make it right.
    """
    url = f"{BASE_URL}{path}"
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            log.warning("attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, path, exc)
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 401:
            raise OpenAQError("401 Unauthorized. Your API key is missing or wrong.")
        if resp.status_code == 410:
            raise OpenAQError(f"410 Gone. {path} is a retired v1/v2 endpoint.")
        if resp.status_code == 422:
            raise OpenAQError(
                f"422 Unprocessable. Your parameters are invalid: {params}. "
                "Common causes: coordinates given as lon,lat instead of lat,lon; "
                "radius above 25000; bbox and coordinates sent together."
            )
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** attempt))
            log.warning("429 rate limited, sleeping %ds", wait)
            time.sleep(wait)
            last_error = "429 rate limited"
            continue
        if resp.status_code >= 500:
            last_error = f"{resp.status_code} server error"
            log.warning("attempt %d/%d got %s", attempt, MAX_RETRIES, resp.status_code)
            time.sleep(2 ** attempt)
            continue

        raise OpenAQError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    raise OpenAQError(f"Gave up on {path} after {MAX_RETRIES} attempts. Last: {last_error}")


def get_pune_locations(parameters_id=PM25_PARAMETER_ID, limit=1000):
    """Every monitoring station within 25km of Pune that measures PM2.5.

    Pass parameters_id=None to get stations measuring anything at all —
    useful on Day 1 when you want to see the full picture before narrowing.
    """
    params = {
        "coordinates": f"{PUNE_LAT},{PUNE_LON}",   # lat,lon. Y,X. Do not swap.
        "radius": RADIUS_M,
        "limit": limit,
    }
    if parameters_id is not None:
        params["parameters_id"] = parameters_id
    return _get("/locations", params)


def get_location_latest(location_id):
    """The most recent reading from every sensor at one station."""
    return _get(f"/locations/{location_id}/latest")


def get_sensor_hours(sensor_id, datetime_from=None, datetime_to=None,
                     limit=1000, page=1):
    """Precomputed hourly averages for one sensor.

    This is the workhorse. It serves both the hourly job (ask for the last
    few hours) and the historical backfill (ask for last March). Same
    endpoint, same parsing, different dates — which is why the backfill on
    Day 5 is much less work than the schedule implies.

    Dates are ISO 8601 strings, e.g. "2026-08-01T00:00:00Z".
    """
    params = {"limit": limit, "page": page}
    if datetime_from:
        params["datetime_from"] = datetime_from
    if datetime_to:
        params["datetime_to"] = datetime_to
    return _get(f"/sensors/{sensor_id}/hours", params)


def iter_sensor_hours(sensor_id, datetime_from=None, datetime_to=None, limit=1000):
    """Walk every page of hourly data for a sensor.

    OpenAQ paginates. If you only read page 1 you silently get the first
    1000 hours of a range and never notice the rest is missing — the kind
    of bug that shows up as a mysteriously flat model six weeks later.
    """
    page = 1
    while True:
        payload = get_sensor_hours(sensor_id, datetime_from, datetime_to,
                                   limit=limit, page=page)
        results = payload.get("results", [])
        if not results:
            return
        yield payload
        if len(results) < limit:
            return                       # short page means it was the last one
        page += 1
        time.sleep(SLEEP_BETWEEN_CALLS)
