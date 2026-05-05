-- Day 4: pure-PostgreSQL contestant.
DROP TABLE IF EXISTS grid_flat;

CREATE UNLOGGED TABLE grid_flat (
    time_step VARCHAR(6) NOT NULL,
    parameter VARCHAR(16) NOT NULL,
    lat_idx   SMALLINT   NOT NULL,
    lon_idx   SMALLINT   NOT NULL,
    value     REAL       NOT NULL
);
