-- PAM v2 schema: expanded metadata for proper polystore
-- Run with: psql -U postgres -d pam -f 01_schema_v2.sql

-- Keep the old table around for benchmarks (rename it)
ALTER TABLE IF EXISTS metadata RENAME TO metadata_v1_legacy;

-- New v2 metadata table with attributes that actually justify a relational DB
CREATE TABLE IF NOT EXISTS metadata (
    id              SERIAL PRIMARY KEY,
    time_step       VARCHAR(6)       NOT NULL,           -- 'YYYYMM' e.g. '201901'
    year            SMALLINT         NOT NULL,
    month           SMALLINT         NOT NULL,
    parameter       VARCHAR(16)      NOT NULL,           -- 'COCL', 'COSC', etc.
    parameter_long  VARCHAR(128),                        -- human-readable name
    units           VARCHAR(32),                         -- 'kg kg-1' etc.
    lat_min         REAL             NOT NULL,           -- spatial bounds in degrees
    lat_max         REAL             NOT NULL,
    lon_min         REAL             NOT NULL,
    lon_max         REAL             NOT NULL,
    n_lat           INTEGER          NOT NULL,           -- grid resolution
    n_lon           INTEGER          NOT NULL,
    tiledb_uri      TEXT             NOT NULL,           -- path to TileDB array
    legacy_npy_path TEXT,                                -- for benchmarks vs v1
    netcdf_source   TEXT,                                -- original .nc4 file
    fill_value      DOUBLE PRECISION,                    -- missing-data sentinel
    data_min        DOUBLE PRECISION,                    -- precomputed stats
    data_max        DOUBLE PRECISION,
    data_mean       DOUBLE PRECISION,
    created_at      TIMESTAMPTZ      DEFAULT NOW(),
    UNIQUE (time_step, parameter)
);

-- Indexes that the IMS cost model will exploit
CREATE INDEX IF NOT EXISTS idx_metadata_time      ON metadata (time_step);
CREATE INDEX IF NOT EXISTS idx_metadata_year_mon  ON metadata (year, month);
CREATE INDEX IF NOT EXISTS idx_metadata_param     ON metadata (parameter);
CREATE INDEX IF NOT EXISTS idx_metadata_bounds    ON metadata (lat_min, lat_max, lon_min, lon_max);

-- Coordinate lookup: maps array index -> real-world degree.
-- Tiny table, but lets us answer "what's the lat at index 100?" without loading the array.
CREATE TABLE IF NOT EXISTS coord_axis (
    parameter   VARCHAR(16)  NOT NULL,
    axis        VARCHAR(8)   NOT NULL,           -- 'lat' or 'lon'
    idx         INTEGER      NOT NULL,
    value       REAL         NOT NULL,
    PRIMARY KEY (parameter, axis, idx)
);

CREATE INDEX IF NOT EXISTS idx_coord_value ON coord_axis (parameter, axis, value);

-- Query log table — for benchmarks and the "show me what the IMS did" UI feature
CREATE TABLE IF NOT EXISTS query_log (
    id              SERIAL PRIMARY KEY,
    received_at     TIMESTAMPTZ DEFAULT NOW(),
    query_json      JSONB,                       -- the parsed user query
    plan_json       JSONB,                       -- the chosen execution plan
    pg_time_ms      REAL,                        -- time spent in PostgreSQL
    array_time_ms   REAL,                        -- time spent in TileDB
    total_time_ms   REAL,
    result_shape    INTEGER[],
    n_files_pruned  INTEGER                      -- files skipped via metadata
);
