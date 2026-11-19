"""Tests that run the project's real SQL against a real Postgres.

    docker compose up -d db
    TEST_DATABASE_URL=postgresql://aqi:localdev@127.0.0.1:5433/aqi python -m pytest tests/test_db_integration.py -v

Without TEST_DATABASE_URL every test here is skipped, so plain `pytest -q` still works with Docker off.
In CI the variable points at a Postgres service container (.github/workflows/ci.yml).

What is real and what is fake:
  real   schema.sql, every query in db.py / ingest.py / dataset.py / forecast.py / service.py /
         seed_local.py / make_readonly_role.py, and Postgres itself
  fake   OpenAQ (ingest's download functions are replaced by a dict of prepared answers)

Safety. These tests create and DROP databases and a role, so:
  * the server must be on this machine (127.0.0.1 / localhost), or nothing runs;
  * they never use the database named in TEST_DATABASE_URL itself. They create their own two scratch
    databases beside it, apply schema.sql there, and drop them at the end;
  * while a test runs, DATABASE_URL points at the scratch database, and the `conn` fixture checks that
    db.get_conn() really landed there BEFORE it empties any table. The cloud database is never touched.
"""

import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd
import psycopg2
import pytest

import dataset
import db
import forecast
import ingest
import make_readonly_role
import seed_local
import service
from openaq_client import OpenAQError

TEST_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL,
                                reason="needs a local Postgres: set TEST_DATABASE_URL (see the top of this file)")

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
SCRATCH, SCRATCH_COPY = "aqi_test_scratch", "aqi_test_scratch_copy"
TEST_ROLE = "aqi_api_test"
SENSOR = service.SENSOR
VERSION = service.MODEL_VERSION
TABLES = "forecasts, measurements, ingestion_runs, sensors, locations"
HOUR = {}                       # "this hour", fixed once per test by the `conn` fixture


def now():
    return datetime.now(timezone.utc)


def ago(hours):
    """The whole hour `hours` before this one (negative = ahead). The same answer all through a test."""
    return HOUR["now"] - timedelta(hours=hours)


# ----------------------------------------------------------------------------- fixtures
def drop_leftovers(cur):
    for name in (SCRATCH, SCRATCH_COPY):
        cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    cur.execute(f"DROP ROLE IF EXISTS {TEST_ROLE}")          # after the databases: its rights lived inside them


@pytest.fixture(scope="module")
def scratch_urls():
    """Two empty databases with schema.sql applied. Made once for this file, dropped at the end."""
    host = urlparse(TEST_URL).hostname
    if host not in LOCAL_HOSTS:
        pytest.fail(f"TEST_DATABASE_URL points at {host}. These tests create and drop databases: "
                    f"they only run against a Postgres on this machine.", pytrace=False)
    try:
        admin = psycopg2.connect(TEST_URL)
    except psycopg2.OperationalError as e:
        pytest.fail(f"cannot reach the test Postgres. Is it running?  docker compose up -d db\n{e}", pytrace=False)
    admin.autocommit = True                                   # CREATE DATABASE cannot run inside a transaction
    urls = {name: urlunparse(urlparse(TEST_URL)._replace(path=f"/{name}")) for name in (SCRATCH, SCRATCH_COPY)}
    with admin.cursor() as cur:
        drop_leftovers(cur)                                   # from a run that was interrupted
        for name in urls:
            cur.execute(f"CREATE DATABASE {name}")
    schema = (ROOT / "schema.sql").read_text()
    for url in urls.values():
        c = psycopg2.connect(url)
        with c, c.cursor() as cur:
            cur.execute(schema)
        c.close()
    yield urls
    with admin.cursor() as cur:
        drop_leftovers(cur)
    admin.close()


@pytest.fixture(autouse=True)
def conn(scratch_urls, monkeypatch):
    """Runs before EVERY test in this file: point the project at the scratch database and empty it.

    Yields a connection to it. Tests that need one name `conn`; the rest are still protected.
    """
    monkeypatch.setenv("DATABASE_URL", scratch_urls[SCRATCH])
    c = db.get_conn()                                         # the project's own way of connecting
    if (c.info.host, c.info.dbname) != (urlparse(TEST_URL).hostname, SCRATCH):
        c.close()
        pytest.fail("db.get_conn() did not land on the scratch database. Nothing was changed.", pytrace=False)
    with c.cursor() as cur:
        cur.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    c.commit()
    for answer in (service.health, service.forecast, service.stats):
        answer.cache_clear()                                  # an answer remembered from another test is stale
    HOUR["now"] = now().replace(minute=0, second=0, microsecond=0)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def keep_out_of_the_real_log():
    """ingest.py writes to logs/ingest.log. A test run must not leave made-up 'sensor failed' lines there.

    Under pytest that handler is normally not even attached (pytest owns the log handlers while it imports
    the modules); this makes sure of it however the tests are started.
    """
    root = logging.getLogger()
    real = [h for h in root.handlers if str(getattr(h, "baseFilename", "")).endswith("ingest.log")]
    for h in real:
        root.removeHandler(h)
    yield
    for h in real:
        root.addHandler(h)


# ----------------------------------------------------------------------------- small builders
def location(location_id, name, sensors):
    return {"location_id": location_id, "name": name, "locality": "Pune", "timezone": "Asia/Kolkata",
            "latitude": 18.5, "longitude": 73.8, "provider": "test", "is_mobile": False, "is_monitor": True,
            "datetime_first": ago(1000), "datetime_last": ago(1),
            "sensors": [{"sensor_id": s, "parameter": "pm25", "units": "µg/m³"} for s in sensors]}


def detail(sensor_id, location_id, active=True):
    return {"sensor_id": sensor_id, "location_id": location_id, "parameter": "pm25", "units": "µg/m³",
            "datetime_first": ago(1000), "datetime_last": ago(1), "observed_count": 500, "avg_value": 40.0,
            "is_active": active}


def register(conn, sensor_id=SENSOR, location_id=1, name="Test station", active=True):
    db.upsert_locations_and_sensors(conn, [location(location_id, name, [sensor_id])])
    db.upsert_sensor_detail(conn, [detail(sensor_id, location_id, active)])


def reading(sensor_id, when, value, source="openaq"):
    return {"sensor_id": sensor_id, "measured_at": when, "value": value, "source": source}


def hourly_readings(oldest, newest, except_hours=()):
    """One reading per hour from `oldest` to `newest` hours ago: a smooth daily wave around 40,
    with nothing in it that the value policy would remove. Hours in `except_hours` are left out."""
    return [reading(SENSOR, ago(h), round(40 + 10 * math.sin(2 * math.pi * h / 24) + 0.3 * (h % 5), 2))
            for h in range(oldest, newest - 1, -1) if h not in except_hours]


def add_forecast(conn, target, point, lower, upper, version=VERSION, tier="full"):
    """A forecast for `target`, made from the hour 24 h before it and issued 20 h before it."""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO forecasts (sensor_id, origin_time, target_time, horizon_hours, point, lower, upper,
                                              model_version, tier, issued_at)
                       VALUES (%s, %s, %s, 24, %s, %s, %s, %s, %s, %s)""",
                    (SENSOR, target - timedelta(hours=24), target, point, lower, upper, version, tier,
                     target - timedelta(hours=20)))
    conn.commit()


def count(conn, table, where="true"):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where}")
        return cur.fetchone()[0]


# ----------------------------------------------------------------------------- schema.sql
def test_schema_can_be_applied_again_and_has_everything(conn):
    with conn.cursor() as cur:
        cur.execute((ROOT / "schema.sql").read_text())            # a second time: nothing may fail
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        names = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'forecasts'")
        forecast_columns = {r[0] for r in cur.fetchall()}
    conn.commit()
    assert names >= {"locations", "sensors", "measurements", "ingestion_runs", "forecasts", "v_features"}
    assert {"tier", "issued_at", "model_version"} <= forecast_columns


def test_the_feature_view_counts_hours_not_rows(conn):
    """v_features lays readings on an hourly grid, so 'one row back' is 'one hour back' even across a hole."""
    register(conn)
    db.insert_measurements(conn, [reading(SENSOR, ago(h), float(h)) for h in (30, 29, 28, 25, 24)])   # 27, 26 missing
    with conn.cursor() as cur:
        cur.execute("SELECT ts, value, lag_1, lag_3 FROM v_features WHERE sensor_id = %s ORDER BY ts", (SENSOR,))
        rows = {r[0]: r[1:] for r in cur.fetchall()}
    assert len(rows) == 7                                          # 7 grid hours for 5 readings
    assert rows[ago(27)] == (None, 28.0, 30.0)                     # a missing hour is a row, not a skip
    assert rows[ago(25)] == (25.0, None, 28.0)                     # lag_1 is the missing hour 26, not hour 28
    assert rows[ago(24)] == (24.0, 25.0, None)


# ----------------------------------------------------------------------------- db.py: the write paths
def test_readings_are_saved_once_however_often_they_are_offered(conn):
    register(conn)
    first = [reading(SENSOR, ago(h), 40.0 + h) for h in (3, 2, 1)]
    assert db.insert_measurements(conn, first) == 3
    assert db.insert_measurements(conn, first) == 0                # the hourly job re-offers the last 72 hours
    assert db.insert_measurements(conn, first + [reading(SENSOR, ago(0), 50.0)]) == 1
    assert db.insert_measurements(conn, [reading(SENSOR, ago(1), 99.0)]) == 0      # and a stored value is never replaced
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM measurements WHERE sensor_id = %s AND measured_at = %s", (SENSOR, ago(1)))
        assert cur.fetchone()[0] == 41.0
    assert db.insert_measurements(conn, [reading(SENSOR, ago(1), 41.5, source="cpcb")]) == 1   # another source, another row
    assert db.insert_measurements(conn, []) == 0
    assert count(conn, "measurements") == 5


def test_a_reading_for_an_unknown_sensor_is_refused(conn):
    """The foreign key: a reading must belong to a registered sensor."""
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        db.insert_measurements(conn, [reading(424242, ago(1), 40.0)])
    conn.rollback()
    assert count(conn, "measurements") == 0


def test_the_station_registry_can_be_refreshed(conn):
    stations = [location(1, "Pashan", [101, 102]), location(2, "Hadapsar", [201])]
    assert db.upsert_locations_and_sensors(conn, stations) == (2, 3)
    stations[0]["datetime_last"] = ago(0)
    assert db.upsert_locations_and_sensors(conn, stations) == (2, 3)          # offered again, stored once
    assert count(conn, "locations") == 2 and count(conn, "sensors") == 3
    assert count(conn, "sensors", "is_active") == 0                           # nothing is live until its detail says so
    assert db.upsert_sensor_detail(conn, [detail(101, 1, active=True)]) == 1
    assert count(conn, "sensors", "is_active") == 1
    assert db.upsert_sensor_detail(conn, []) == 0


def test_every_run_leaves_a_row(conn):
    run_id = db.start_run(conn, source="openaq", mode="live")
    assert count(conn, "ingestion_runs", "status = 'running' AND finished_at IS NULL") == 1
    db.finish_run(conn, run_id, "ok", sensors_tried=13, rows_fetched=900, rows_inserted=12)
    with conn.cursor() as cur:
        cur.execute("SELECT status, sensors_tried, rows_fetched, rows_inserted, finished_at >= run_at, error_text "
                    "FROM ingestion_runs WHERE id = %s", (run_id,))
        assert cur.fetchone() == ("ok", 13, 900, 12, True, None)


# ----------------------------------------------------------------------------- ingest.py with a fake OpenAQ
@pytest.fixture
def fake_openaq(monkeypatch):
    """A dict to fill in: sensor id -> list of pages (each a list of readings), or an OpenAQError to raise."""
    answers = {}

    def fake_iter(sensor_id, datetime_from=None, datetime_to=None, limit=1000):
        answer = answers.get(sensor_id, [])
        if isinstance(answer, Exception):
            raise answer
        yield from answer

    monkeypatch.setattr(ingest, "iter_sensor_hours", fake_iter)
    monkeypatch.setattr(ingest, "flatten_hours", lambda payload, sensor_id: payload)   # the pages are rows already
    return answers


def last_run(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT status, mode, sensors_tried, rows_fetched, rows_inserted, error_text "
                    "FROM ingestion_runs ORDER BY id DESC LIMIT 1")
        return cur.fetchone()


def test_only_one_live_sensor_per_station_is_polled(conn):
    register(conn, sensor_id=101, location_id=1, name="Pashan")
    register(conn, sensor_id=102, location_id=1, name="Pashan", active=False)       # the retired instrument
    register(conn, sensor_id=201, location_id=2, name="Hadapsar")
    register(conn, sensor_id=301, location_id=3, name="Katraj", active=False)       # a dead station
    assert ingest.active_sensors(conn) == [(101, "Pashan"), (201, "Hadapsar")]


def test_a_run_saves_new_readings_and_a_second_run_saves_none(conn, fake_openaq):
    register(conn, sensor_id=101, location_id=1, name="Pashan")
    register(conn, sensor_id=201, location_id=2, name="Hadapsar")
    fake_openaq[101] = [[reading(101, ago(3), 40.0), reading(101, ago(2), 41.0)], [reading(101, ago(1), 42.0)]]
    fake_openaq[201] = [[reading(201, ago(2), 55.0)]]
    assert ingest.run_ingest(conn, "from", "to", mode="live") == (4, 4)
    assert last_run(conn) == ("ok", "live", 2, 4, 4, None)
    assert ingest.run_ingest(conn, "from", "to", mode="live") == (4, 0)             # 4 seen, 0 new
    assert last_run(conn) == ("ok", "live", 2, 4, 0, None)
    assert count(conn, "measurements") == 4 and count(conn, "ingestion_runs") == 2


def test_one_failing_station_does_not_stop_the_others(conn, fake_openaq):
    register(conn, sensor_id=101, location_id=1, name="Pashan")
    register(conn, sensor_id=201, location_id=2, name="Hadapsar")
    fake_openaq[101] = OpenAQError("Gave up on /sensors/101/hours after 3 attempts")
    fake_openaq[201] = [[reading(201, ago(1), 55.0)]]
    assert ingest.run_ingest(conn, "from", "to", mode="live") == (1, 1)
    status, _, tried, _, inserted, error = last_run(conn)
    assert (status, tried, inserted) == ("partial", 2, 1)
    assert "sensor 101 (Pashan)" in error and "Gave up" in error

    fake_openaq[201] = OpenAQError("503 server error")                              # now every sensor fails
    ingest.run_ingest(conn, "from", "to", mode="live")
    assert last_run(conn)[0] == "failed"


def test_a_run_with_no_registered_sensors_is_recorded_as_failed(conn, fake_openaq):
    assert ingest.run_ingest(conn, "from", "to", mode="backfill") == (0, 0)
    status, mode, _, _, _, error = last_run(conn)
    assert (status, mode) == ("failed", "backfill") and "--discover" in error


def test_discovery_registers_stations_then_finds_the_live_sensor_of_each(conn, monkeypatch):
    """Pass 1 lists stations. Pass 2 asks each station which of its sensors is still reporting."""
    stations = [location(1, "Pashan", [101, 102]), location(2, "Hadapsar", [201]), location(3, "Katraj", [301])]
    per_station = {1: [detail(101, 1, active=False), detail(102, 1, active=True)],   # retired, then its replacement
                   2: [detail(201, 2, active=True)],
                   3: OpenAQError("503 server error")}                               # this request fails

    def fake_station_sensors(location_id):
        answer = per_station[location_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ingest, "get_pune_locations", lambda parameters_id=2: stations)
    monkeypatch.setattr(ingest, "flatten_locations", lambda payload: payload)
    monkeypatch.setattr(ingest, "get_location_sensors", fake_station_sensors)
    monkeypatch.setattr(ingest, "flatten_location_sensors", lambda payload, location_id: payload)
    monkeypatch.setattr(ingest.time, "sleep", lambda seconds: None)

    assert ingest.discover(conn) == (3, 2)                    # 3 stations registered, 2 sensors known to be live
    assert ingest.active_sensors(conn) == [(102, "Pashan"), (201, "Hadapsar")]      # the failed station: not polled


def test_the_command_line_decides_the_window(conn, monkeypatch):
    asked = []
    monkeypatch.setattr(ingest, "run_ingest", lambda c, dt_from, dt_to, mode: asked.append((dt_from, dt_to, mode)))
    monkeypatch.setattr(ingest, "discover", lambda c: asked.append("discover"))

    def as_time(text):
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")

    monkeypatch.setattr(sys, "argv", ["ingest.py", "--from", "2024-01-01", "--to", "2024-02-01"])
    ingest.main()
    assert asked[-1] == ("2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z", "backfill")

    monkeypatch.setattr(sys, "argv", ["ingest.py", "--hours-back", "72"])           # what the hourly job runs
    ingest.main()
    start, end, mode = asked[-1]
    assert mode == "live" and as_time(end) - as_time(start) == timedelta(hours=72)
    assert as_time(end).minute == 0                                                 # whole hours only

    monkeypatch.setattr(sys, "argv", ["ingest.py", "--discover"])                   # refresh the registry, then stop
    ingest.main()
    assert asked[-1] == "discover" and len(asked) == 3


# ----------------------------------------------------------------------------- dataset.py: reading back
def test_readings_load_sorted_for_one_sensor_and_one_source(conn):
    register(conn)
    register(conn, sensor_id=777, location_id=2, name="Other")
    db.insert_measurements(conn, [reading(SENSOR, ago(1), 3.0), reading(SENSOR, ago(5), 1.0),
                                  reading(SENSOR, ago(3), 2.0), reading(SENSOR, ago(3), 99.0, source="cpcb"),
                                  reading(777, ago(2), 50.0)])
    s = dataset.load_readings(SENSOR)
    assert list(s) == [1.0, 2.0, 3.0] and list(s.index) == [ago(5), ago(3), ago(1)]
    assert str(s.index.tz) == "UTC"
    assert list(dataset.load_readings(SENSOR, since=ago(4))) == [2.0, 3.0]


# ----------------------------------------------------------------------------- forecast.py
def forecast_frame(hours_ahead, point, tier="full"):
    targets = pd.DatetimeIndex([ago(-h) for h in hours_ahead])
    return pd.DataFrame({"sensor_id": SENSOR, "origin_time": targets - pd.Timedelta(hours=24), "target_time": targets,
                         "horizon_hours": 24, "point": point, "lower": point * 0.7, "upper": point * 1.4,
                         "model_version": VERSION, "tier": tier})[forecast.COLUMNS]


def test_a_forecast_is_written_once_and_never_changed(conn):
    assert forecast.write_rows(conn, forecast_frame([2, 3], point=50.0)) == 2
    assert forecast.write_rows(conn, forecast_frame([2, 3], point=50.0)) == 0
    # a later run with a different opinion about the same two hours, plus one new hour
    assert forecast.write_rows(conn, forecast_frame([2, 3, 4], point=80.0, tier="short")) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT point, tier FROM forecasts ORDER BY target_time")
        assert cur.fetchall() == [(50.0, "full"), (50.0, "full"), (80.0, "short")]


@pytest.fixture
def run_forecast(monkeypatch, capsys):
    """Run forecast.py's main() as the hourly job does, half past the current hour. Returns what it printed."""
    def run(*flags):
        run_at = (ago(0) + timedelta(minutes=30)).isoformat()
        monkeypatch.setattr(sys, "argv", ["forecast.py", "--now", run_at, *flags])
        assert forecast.main() == 0
        return capsys.readouterr().out
    return run


def test_the_hourly_forecast_step_from_readings_to_rows(conn, run_forecast):
    """forecast.py end to end: read the database, build features, apply the model file, write rows."""
    register(conn)
    db.insert_measurements(conn, hourly_readings(240, 3))            # ten days, every hour; the newest is 3 h old

    assert "DRY RUN" in run_forecast("--dry-run")
    assert count(conn, "forecasts") == 0                             # a dry run writes nothing

    # origin hours 23 h ago ... 3 h ago = 21 hours, each with a full week behind it
    assert "21 new rows (0 already issued)" in run_forecast()
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), min(target_time), max(target_time),
                              bool_and(target_time = origin_time + interval '24 hours'),
                              bool_and(0 <= lower AND lower <= point AND point <= upper),
                              array_agg(DISTINCT tier), array_agg(DISTINCT model_version)
                       FROM forecasts WHERE sensor_id = %s""", (SENSOR,))
        assert cur.fetchone() == (21, ago(-1), ago(-21), True, True, ["full"], [VERSION])
    conn.commit()

    assert "0 new rows (21 already issued)" in run_forecast()        # the next run, no new reading: nothing to add
    db.insert_measurements(conn, [reading(SENSOR, ago(2), 41.0)])    # one more hour arrives from the station
    assert "1 new rows (21 already issued)" in run_forecast()
    assert count(conn, "forecasts") == 22


def test_the_forecast_step_with_too_little_data_says_so_and_writes_nothing(conn, run_forecast):
    register(conn)
    assert "nothing to forecast" in run_forecast()                   # no readings at all
    db.insert_measurements(conn, hourly_readings(4, 3))              # two readings: even the 3 h model lacks its lags
    assert "nothing to issue this run" in run_forecast()
    assert count(conn, "forecasts") == 0


def test_after_a_hole_in_the_data_the_smaller_tiers_keep_the_forecasts_coming(conn, run_forecast):
    """Two 5-hour holes. An origin hour whose 24 h lag falls in a hole can only use the 3 h model ('short');
    one whose 48 h lag falls in a hole can still use the 24 h model ('day'). Nothing goes unforecast."""
    register(conn)
    holes = set(range(36, 41)) | set(range(56, 61))                  # 36-40 h ago and 56-60 h ago: no readings
    db.insert_measurements(conn, hourly_readings(240, 3, except_hours=holes))
    run_forecast()
    with conn.cursor() as cur:
        cur.execute("SELECT tier, count(*) FROM forecasts GROUP BY tier ORDER BY tier")
        by_tier = dict(cur.fetchall())
        cur.execute("SELECT origin_time, tier FROM forecasts ORDER BY origin_time DESC")
        tier_at = {origin: tier for origin, tier in cur.fetchall()}
    assert by_tier == {"full": 12, "day": 4, "short": 5}             # 21 of 21 origin hours forecast
    assert all(tier_at[ago(h)] == "short" for h in range(12, 17))    # their lag_24 is 36-40 h ago: in the hole
    assert all(tier_at[ago(h)] == "day" for h in range(8, 12))       # their lag_48 is 56-59 h ago: in the hole


# ----------------------------------------------------------------------------- service.py: what the API reads
def test_forecast_query_serves_only_hours_ahead_from_the_current_model(conn):
    register(conn, name="Panchawati_Pashan, Pune - IITM")
    add_forecast(conn, ago(2), 40, 30, 50)                                  # already in the past
    add_forecast(conn, ago(-3), 60, 45, 80, tier="day")
    add_forecast(conn, ago(-2), 50, 35, 70)
    add_forecast(conn, ago(-4), 99, 90, 110, version="v1")                   # the previous model's opinion
    out = service.forecast()
    assert out["station"] == "Panchawati_Pashan, Pune - IITM" and out["model_version"] == VERSION
    assert [(f["target_time"], f["point"], f["tier"]) for f in out["forecasts"]] == \
        [(ago(-2), 50.0, "full"), (ago(-3), 60.0, "day")]                   # soonest first
    assert out["data_as_of"] == ago(-3) - timedelta(hours=24)               # the newest origin hour used


def test_forecast_query_with_nothing_on_file_is_an_empty_list(conn):
    register(conn)
    out = service.forecast()
    assert out["forecasts"] == [] and out["data_as_of"] is None


def test_stats_score_each_forecast_against_the_reading_that_arrived(conn):
    register(conn)
    cases = [  # target (hours ago), point, lower, upper, tier, actual, reading at the origin hour (= persistence)
        (5, 50, 40, 60, "full", 55.0, 60.0),      # off by 5, inside the band;  persistence off by 5
        (4, 80, 70, 90, "full", 100.0, 90.0),     # off by 20, outside;         persistence off by 10
        (3, 30, 20, 45, "day", 25.0, 35.0),       # off by 5, inside;           persistence off by 10
        (2, 40, 30, 50, "full", 0.0, 40.0),       # actual 0: a broken reading, not scored (value policy)
        (1, 40, 30, 50, "full", 990.0, 40.0),     # actual 990: the instrument's ceiling, not scored
    ]
    for h, point, lower, upper, tier, actual, origin_value in cases:
        add_forecast(conn, ago(h), point, lower, upper, tier=tier)
        db.insert_measurements(conn, [reading(SENSOR, ago(h), actual), reading(SENSOR, ago(h + 24), origin_value)])
    add_forecast(conn, ago(-3), 45, 35, 60)                                  # still ahead: nothing to score yet
    add_forecast(conn, ago(6), 10, 5, 15, version="v1")                      # the previous model's record
    db.insert_measurements(conn, [reading(SENSOR, ago(6), 12.0)])

    out = service.stats()
    live = out["live"]
    assert live["scored_hours"] == 3
    assert live["mae"] == 10.0                    # (5 + 20 + 5) / 3
    assert live["bias"] == -6.67                  # (-5 - 20 + 5) / 3: the forecasts ran low
    assert live["coverage_80"] == 0.667           # 2 of 3 inside the band
    assert live["mean_width"] == 21.7             # (20 + 20 + 25) / 3
    assert live["persistence_mae"] == 8.33        # (5 + 10 + 10) / 3

    by_tier = {t["tier"]: t for t in out["live_by_tier"]}
    assert (by_tier["full"]["scored_hours"], by_tier["full"]["mae"]) == (2, 12.5)
    assert (by_tier["day"]["scored_hours"], by_tier["day"]["mae"]) == (1, 5.0)
    by_version = {v["model_version"]: v for v in out["live_by_version"]}
    assert (by_version["v1"]["scored_hours"], by_version["v1"]["mae"]) == (1, 2.0)   # the old record stays visible
    assert by_version[VERSION]["scored_hours"] == 3

    assert out["lead_time"]["forecasts_issued"] == 6           # this version: five past and one ahead
    assert out["lead_time"]["mean_lead_hours"] == 20.0         # every forecast here was issued 20 h before its hour
    assert out["availability_7d"]["hours_with_forecast"] == 6  # past hours with a forecast, from any version


def test_health_gives_two_separate_verdicts(conn):
    """Our job late = broken. Their data late = upstream_lag. The same rule as healthcheck.py."""
    register(conn)

    def health_when(run_hours_ago, reading_hours_ago):
        with conn.cursor() as cur:
            cur.execute("TRUNCATE ingestion_runs, measurements")
            cur.execute("INSERT INTO ingestion_runs (run_at, source, mode, status) VALUES (%s, 'openaq', 'live', 'ok')",
                        (now() - timedelta(hours=run_hours_ago),))
            cur.execute("INSERT INTO ingestion_runs (run_at, source, mode, status) "
                        "VALUES (now(), 'openaq', 'live', 'failed')")
        conn.commit()
        db.insert_measurements(conn, [reading(SENSOR, now() - timedelta(hours=reading_hours_ago), 40.0)])
        service.health.cache_clear()
        return service.health()

    fresh = health_when(run_hours_ago=1, reading_hours_ago=2)
    assert fresh["status"] == "ok"
    assert fresh["pipeline"]["runs_last_24h"] == 1                           # the failed run does not count
    assert health_when(1, service.UPSTREAM_HOURS + 1)["status"] == "upstream_lag"
    assert health_when(service.STALE_HOURS + 1, 2)["status"] == "broken"
    assert health_when(service.STALE_HOURS + 1, 30)["status"] == "broken"     # both late: ours is the one to fix


def test_health_on_an_empty_database_is_broken_not_a_crash(conn):
    out = service.health()
    assert out["status"] == "broken" and out["data"]["newest_reading"] is None


def test_an_answer_is_reused_until_its_time_is_up(conn):
    """The cache in front of the queries: a second request inside the window does not see new rows."""
    register(conn)
    add_forecast(conn, ago(-2), 50, 35, 70)
    assert len(service.forecast()["forecasts"]) == 1
    add_forecast(conn, ago(-3), 60, 45, 80)
    assert len(service.forecast()["forecasts"]) == 1                         # still the remembered answer
    service.forecast.cache_clear()                                           # what 60 seconds passing does
    assert len(service.forecast()["forecasts"]) == 2


# ----------------------------------------------------------------------------- seed_local.py
def test_copying_to_a_local_database_is_complete_and_repeatable(conn, scratch_urls):
    register(conn)
    db.insert_measurements(conn, [reading(SENSOR, ago(h), 40.0 + h) for h in (1, 2, 3, 24 * 40)])   # one is 40 days old
    for _ in range(3):
        db.finish_run(conn, db.start_run(conn, "openaq", "live"), "ok")
    add_forecast(conn, ago(-2), 50, 35, 70)

    target = psycopg2.connect(scratch_urls[SCRATCH_COPY])
    try:
        with target.cursor() as cur:
            cur.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        target.commit()
        since = {"since": now() - timedelta(days=30)}
        first = {t: seed_local.copy_table(conn, target, t, where, since) for t, where in seed_local.TABLES}
        again = {t: seed_local.copy_table(conn, target, t, where, since) for t, where in seed_local.TABLES}
        assert first == {"locations": (1, 1), "sensors": (1, 1), "measurements": (3, 3),       # the old reading is left out
                         "ingestion_runs": (3, 3), "forecasts": (1, 1)}                        # (rows read, rows new)
        assert all(new == 0 for _, new in again.values())                                       # nothing is copied twice
        # the run counter was moved past the copied ids, so the next local run does not collide with them
        assert db.start_run(target, "openaq", "live") == 4
    finally:
        target.close()


# ----------------------------------------------------------------------------- make_readonly_role.py
def test_the_api_role_can_read_and_cannot_write(conn, scratch_urls):
    register(conn)
    db.insert_measurements(conn, [reading(SENSOR, ago(1), 40.0)])
    password = make_readonly_role.new_password()
    assert make_readonly_role.create_or_rotate(conn, TEST_ROLE, password, make_readonly_role.TABLES) == "created"

    url = make_readonly_role.url_for_role(scratch_urls[SCRATCH], TEST_ROLE, password)
    counts, write_refused = make_readonly_role.check(url, make_readonly_role.TABLES)
    assert counts["measurements"] == 1 and set(counts) == set(make_readonly_role.TABLES)
    assert write_refused
    assert count(conn, "pg_roles", f"rolname = '{TEST_ROLE}' AND rolconnlimit = 10 AND NOT rolsuper") == 1

    as_role = psycopg2.connect(url)
    try:
        with as_role.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            assert cur.fetchone()[0] == "5s"                                   # a runaway query is cut off
            for forbidden in ("INSERT INTO measurements (sensor_id, measured_at, value) VALUES (1, now(), 1)",
                              "UPDATE forecasts SET point = 0",
                              "DELETE FROM ingestion_runs",
                              "CREATE TABLE sneaky (x int)",
                              "DROP TABLE forecasts"):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(forbidden)
                as_role.rollback()
    finally:
        as_role.close()

    # a new password: same role, and the old connection string stops working
    newer = make_readonly_role.new_password()
    assert make_readonly_role.create_or_rotate(conn, TEST_ROLE, newer, make_readonly_role.TABLES) == "rotated"
    with pytest.raises(psycopg2.OperationalError):
        psycopg2.connect(url)
    still_read_only = make_readonly_role.check(
        make_readonly_role.url_for_role(scratch_urls[SCRATCH], TEST_ROLE, newer), make_readonly_role.TABLES)[1]
    assert still_read_only
