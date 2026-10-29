-- schema.sql
-- Apply with:  python apply_schema.py   (uses DATABASE_URL if set, else the local PG* settings)
-- Every statement is IF NOT EXISTS / OR REPLACE, so it is safe to run again and again.
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
    sensor_id       INTEGER PRIMARY KEY,        -- OpenAQ's id
    location_id     INTEGER NOT NULL REFERENCES locations(location_id),
    parameter       TEXT NOT NULL,              -- 'pm25', 'pm10', 'no2', ...
    units           TEXT,
    -- Per-sensor dates, NOT the location's. A station can hold a retired
    -- sensor and a live replacement; the location's own date range is the
    -- union of both and hides the gap between them. Several Pune stations
    -- have a 2.5 year hole that is completely invisible at location level.
    datetime_first  TIMESTAMPTZ,
    datetime_last   TIMESTAMPTZ,
    observed_count  INTEGER,
    avg_value       DOUBLE PRECISION,
    is_active       BOOLEAN NOT NULL DEFAULT false,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_checked    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sensors_location  ON sensors (location_id);
CREATE INDEX IF NOT EXISTS idx_sensors_parameter ON sensors (parameter);
CREATE INDEX IF NOT EXISTS idx_sensors_active    ON sensors (is_active) WHERE is_active;

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
-- (This is also what makes healthcheck's max(measured_at) an Index Only Scan Backward, 0.03 ms.)
CREATE INDEX IF NOT EXISTS idx_measurements_time   ON measurements (measured_at);

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

-- v_features: the training table, built the time-correct way (Step 4, 29 Oct 2026).
--
-- Rows are HOURS on a regular grid (generate_series), not readings. On the grid,
-- "24 rows back" IS "24 hours back", so LAG/LEAD and ROWS frames are safe.
-- A missing hour is a row with value NULL -- never silently skipped. (On the raw
-- table, avg over 24 ROWS reached 41 hours back after a 17-hour gap: 80.4 vs 88.5.)
--
-- Columns: value at ts; lag_k = value k hours earlier; roll_24 / roll_168 = mean of
-- the previous 24 / 168 hours, with n_24 / n_168 = how many of those hours existed;
-- hour/dow/month in IST; y_24h_ahead = value 24 hours later (the forecasting target).
CREATE OR REPLACE VIEW v_features AS
WITH ids AS (
    SELECT sensor_id, min(measured_at) AS first_ts, max(measured_at) AS last_ts
    FROM measurements
    GROUP BY sensor_id
),
grid AS (
    SELECT i.sensor_id, g.ts
    FROM ids i
    CROSS JOIN LATERAL generate_series(i.first_ts, i.last_ts, interval '1 hour') AS g(ts)
),
joined AS (
    SELECT g.sensor_id, g.ts, m.value
    FROM grid g
    LEFT JOIN measurements m
           ON m.sensor_id = g.sensor_id AND m.measured_at = g.ts AND m.source = 'openaq'
)
SELECT sensor_id,
       ts,
       value,
       LAG(value, 1)   OVER w AS lag_1,
       LAG(value, 2)   OVER w AS lag_2,
       LAG(value, 3)   OVER w AS lag_3,
       LAG(value, 6)   OVER w AS lag_6,
       LAG(value, 12)  OVER w AS lag_12,
       LAG(value, 24)  OVER w AS lag_24,
       LAG(value, 48)  OVER w AS lag_48,
       LAG(value, 168) OVER w AS lag_168,
       avg(value)   OVER (w ROWS BETWEEN 23  PRECEDING AND CURRENT ROW) AS roll_24,
       count(value) OVER (w ROWS BETWEEN 23  PRECEDING AND CURRENT ROW) AS n_24,
       avg(value)   OVER (w ROWS BETWEEN 167 PRECEDING AND CURRENT ROW) AS roll_168,
       count(value) OVER (w ROWS BETWEEN 167 PRECEDING AND CURRENT ROW) AS n_168,
       EXTRACT(HOUR  FROM ts AT TIME ZONE 'Asia/Kolkata')::int AS hour_ist,
       EXTRACT(DOW   FROM ts AT TIME ZONE 'Asia/Kolkata')::int AS dow_ist,
       EXTRACT(MONTH FROM ts AT TIME ZONE 'Asia/Kolkata')::int AS month_ist,
       LEAD(value, 24) OVER w AS y_24h_ahead
FROM joined
WINDOW w AS (PARTITION BY sensor_id ORDER BY ts);