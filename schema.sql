-- schema.sql
-- Run once:  psql -h localhost -U postgres -d aqi -f schema.sql
--
-- Design note (worth being able to explain in an interview):
-- OpenAQ v3 is organised as location -> sensor -> measurement.
-- A "location" is a physical monitoring station.
-- A "sensor" is one instrument at that station measuring one parameter.
-- So a station measuring PM2.5, PM10 and NO2 has three sensors.
-- We mirror that structure instead of flattening it, because sensor_id
-- is the only stable key the API gives us for a measurement series.

CREATE TABLE IF NOT EXISTS locations (
    location_id     INTEGER PRIMARY KEY,      -- OpenAQ's id, not ours
    name            TEXT NOT NULL,
    locality        TEXT,
    timezone        TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    provider        TEXT,
    is_mobile       BOOLEAN,
    is_monitor      BOOLEAN,                  -- false = low-cost sensor, treat with suspicion
    datetime_first  TIMESTAMPTZ,              -- earliest data OpenAQ holds for this station
    datetime_last   TIMESTAMPTZ,              -- most recent; if this is old, the station is dead
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_checked    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sensors (
    sensor_id    INTEGER PRIMARY KEY,         -- OpenAQ's id
    location_id  INTEGER NOT NULL REFERENCES locations(location_id),
    parameter    TEXT NOT NULL,               -- 'pm25', 'pm10', 'no2', ...
    units        TEXT,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sensors_location  ON sensors (location_id);
CREATE INDEX IF NOT EXISTS idx_sensors_parameter ON sensors (parameter);

-- The table that actually matters.
--
-- The PRIMARY KEY is what stops duplicates. Because it is (sensor_id,
-- measured_at, source), the same reading from the same sensor at the same
-- hour can only exist once per source. That is what lets you run the
-- ingest job as often as you like without the row count inflating, and it
-- is what makes the backfill safe to re-run after it crashes halfway.
CREATE TABLE IF NOT EXISTS measurements (
    sensor_id    INTEGER NOT NULL REFERENCES sensors(sensor_id),
    measured_at  TIMESTAMPTZ NOT NULL,        -- always UTC. Convert to IST only when showing a human.
    value        DOUBLE PRECISION NOT NULL,
    source       TEXT NOT NULL DEFAULT 'openaq',
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sensor_id, measured_at, source)
);

-- measured_at first: most of your queries filter by time across many sensors.
CREATE INDEX IF NOT EXISTS idx_measurements_time   ON measurements (measured_at);
CREATE INDEX IF NOT EXISTS idx_measurements_sensor ON measurements (sensor_id, measured_at);

-- Every run of the ingest job writes one row here, success or failure.
-- This table is the evidence behind the "ran continuously for N days"
-- claim on your resume. Do not delete rows from it.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id             BIGSERIAL PRIMARY KEY,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    source         TEXT NOT NULL,             -- 'openaq', later 'cpcb'
    mode           TEXT NOT NULL,             -- 'live' or 'backfill'
    sensors_tried  INTEGER NOT NULL DEFAULT 0,
    rows_fetched   INTEGER NOT NULL DEFAULT 0,
    rows_inserted  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL,             -- 'running', 'ok', 'partial', 'failed'
    error_text     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_run_at ON ingestion_runs (run_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON ingestion_runs (status);
