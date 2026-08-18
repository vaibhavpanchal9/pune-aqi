"""Day 5, task 7 — brought forward, because you need it on Day 2.

These tests need no network and no database. They run in milliseconds.
That is the entire point of keeping transform.py pure.

    pytest -q
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from transform import (flatten_locations, flatten_hours, flatten_latest,
                       summarise_locations, _parse_dt)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    with open(FIXTURES / name) as fh:
        return json.load(fh)


# --------------------------------------------------------------- locations

def test_flatten_locations_returns_one_row_per_station():
    locations = flatten_locations(load("locations_sample.json"))
    assert len(locations) == 2


def test_flatten_locations_reads_the_fields_we_care_about():
    karve = flatten_locations(load("locations_sample.json"))[0]
    assert karve["location_id"] == 8118
    assert karve["name"] == "Karve Road, Pune"
    assert karve["latitude"] == pytest.approx(18.5018)
    assert karve["longitude"] == pytest.approx(73.8206)
    assert karve["provider"] == "AirNow"
    assert karve["is_monitor"] is True


def test_latitude_is_not_silently_swapped_with_longitude():
    """Pune sits near 18.5 N, 73.8 E.

    If latitude and longitude ever get swapped, this test fails. Without
    it, a swap produces perfectly valid-looking rows describing a spot in
    the Indian Ocean, and nothing else in the pipeline would object.
    """
    for loc in flatten_locations(load("locations_sample.json")):
        assert 17.0 < loc["latitude"] < 20.0, "latitude out of range for Pune"
        assert 72.0 < loc["longitude"] < 75.0, "longitude out of range for Pune"


def test_sensors_are_nested_under_their_station():
    locations = flatten_locations(load("locations_sample.json"))
    karve, hadapsar = locations
    assert len(karve["sensors"]) == 2
    assert {s["parameter"] for s in karve["sensors"]} == {"pm25", "pm10"}
    assert len(hadapsar["sensors"]) == 1
    assert karve["sensors"][0]["sensor_id"] == 23534


def test_timestamps_are_parsed_as_utc_aware():
    karve = flatten_locations(load("locations_sample.json"))[0]
    assert karve["datetime_last"].tzinfo is not None
    assert karve["datetime_last"] == datetime(2026, 8, 17, 6, 0, tzinfo=timezone.utc)


def test_we_keep_utc_not_local_time():
    """The fixture's local time is 11:30 IST; UTC is 06:00.

    If this ever returns hour 11, someone has started reading the "local"
    field, and every downstream hour-of-day feature becomes wrong by 5.5.
    """
    karve = flatten_locations(load("locations_sample.json"))[0]
    assert karve["datetime_last"].hour == 6


# ------------------------------------------------------------------ hours

def test_flatten_hours_drops_null_values_but_keeps_real_zeros():
    """The fixture has 5 hours: 3 normal, 1 null, 1 that is genuinely 0.0.

    Null means the sensor was down. Zero means it measured zero. Collapsing
    the two would invent clean-air readings out of missing data.
    """
    rows = flatten_hours(load("hours_sample.json"), sensor_id=23534)
    assert len(rows) == 4
    values = [r["value"] for r in rows]
    assert 0.0 in values
    assert None not in values


def test_flatten_hours_uses_the_start_of_the_hour():
    rows = flatten_hours(load("hours_sample.json"), sensor_id=23534)
    assert rows[0]["measured_at"] == datetime(2026, 8, 16, 18, 0, tzinfo=timezone.utc)


def test_flatten_hours_stamps_every_row_with_its_sensor():
    rows = flatten_hours(load("hours_sample.json"), sensor_id=23534)
    assert all(r["sensor_id"] == 23534 for r in rows)
    assert all(r["source"] == "openaq" for r in rows)


def test_flatten_hours_produces_no_duplicate_timestamps():
    """The database primary key would reject duplicates anyway, but silently.

    Catching it here tells you the parser is wrong; catching it there just
    tells you the insert count was lower than you expected.
    """
    rows = flatten_hours(load("hours_sample.json"), sensor_id=23534)
    stamps = [r["measured_at"] for r in rows]
    assert len(stamps) == len(set(stamps))


def test_empty_payload_is_not_an_error():
    assert flatten_hours({"results": []}, sensor_id=1) == []
    assert flatten_hours({}, sensor_id=1) == []
    assert flatten_locations({}) == []


# ----------------------------------------------------------------- latest

def test_flatten_latest_reads_sensor_id_from_the_record():
    payload = {
        "results": [
            {"datetime": {"utc": "2026-08-17T06:00:00Z", "local": "..."},
             "value": 44.1, "sensorsId": 23534, "locationsId": 8118},
            {"datetime": {"utc": "2026-08-17T06:00:00Z", "local": "..."},
             "value": None, "sensorsId": 23535, "locationsId": 8118},
        ]
    }
    rows = flatten_latest(payload)
    assert len(rows) == 1
    assert rows[0]["sensor_id"] == 23534


# ---------------------------------------------------------------- summary

def test_summary_puts_pm25_stations_with_fresh_data_first():
    locations = flatten_locations(load("locations_sample.json"))
    rows = summarise_locations(locations, parameter="pm25")
    assert rows[0]["name"] == "Karve Road, Pune"
    assert rows[0]["has_pm25"] is True


def test_summary_flags_stale_stations():
    """Hadapsar's last reading is Nov 2025. It should look very stale."""
    locations = flatten_locations(load("locations_sample.json"))
    rows = summarise_locations(locations)
    stale = [r for r in rows if r["name"].startswith("Hadapsar")][0]
    assert stale["days_stale"] > 200


def test_summary_distinguishes_reference_monitors_from_low_cost_sensors():
    """PurpleAir nodes and government monitors are not interchangeable.

    Mixing them without noticing is a real modelling error, so the
    distinction has to survive into the summary.
    """
    locations = flatten_locations(load("locations_sample.json"))
    rows = summarise_locations(locations)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Karve Road, Pune"]["is_monitor"] is True
    assert by_name["Hadapsar low-cost node"]["is_monitor"] is False


# -------------------------------------------------------------- date edge

def test_parse_dt_handles_missing_nodes():
    assert _parse_dt(None) is None
    assert _parse_dt({}) is None
    assert _parse_dt({"utc": None}) is None


def test_parse_dt_handles_trailing_z():
    dt = _parse_dt({"utc": "2026-08-16T18:00:00Z"})
    assert dt == datetime(2026, 8, 16, 18, 0, tzinfo=timezone.utc)
