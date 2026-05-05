"""
PAM v2 — build_tiledb.py

One-shot migration script. Reads every .nc4 file in dataset/, builds a unified
3D TileDB dense array (time x lat x lon), and populates the new metadata + coord_axis
tables in PostgreSQL.

Run once after applying 01_schema_v2.sql:
    python build_tiledb.py

Idempotent: drops and recreates the TileDB array each run.
"""
import os
import shutil
import numpy as np
import xarray as xr
import tiledb
import psycopg2
from psycopg2.extras import execute_values

INPUT_DIR    = "dataset"
TILEDB_URI   = "tiledb_store/pam_co"
PARAMETER    = "COCL"               # MERRA-2 carbon monoxide column burden
LEGACY_DIR   = "grids"              # keep .npy files for benchmark baseline

PG = dict(dbname="pam", user="postgres", password="postgres", host="localhost")


def discover_files():
    """Return sorted list of (time_step, full_path) for every .nc4 in INPUT_DIR."""
    out = []
    for f in sorted(os.listdir(INPUT_DIR)):
        if f.endswith(".nc4"):
            # Filename pattern: MERRA2_400.tavgM_2d_chm_Nx.YYYYMM.nc4
            time_step = f.split(".")[2]
            out.append((time_step, os.path.join(INPUT_DIR, f)))
    return out


def inspect_first(path):
    """Open one file to learn dimensions, lat/lon coords, attribute metadata."""
    ds = xr.open_dataset(path)
    var = ds[PARAMETER]
    # MERRA-2 monthly-mean files have shape (1, 361, 576) — squeeze the time axis
    arr = var.values.squeeze()
    lat = ds["lat"].values.astype(np.float32)
    lon = ds["lon"].values.astype(np.float32)
    units = var.attrs.get("units", "")
    long_name = var.attrs.get("long_name", "")
    fill_val = var.attrs.get("_FillValue") or var.attrs.get("missing_value")
    ds.close()
    return arr.shape, lat, lon, units, long_name, fill_val


def create_tiledb_array(n_time, n_lat, n_lon):
    """Create the unified dense array with chunked tiling."""
    if os.path.exists(TILEDB_URI):
        shutil.rmtree(TILEDB_URI)
    os.makedirs(os.path.dirname(TILEDB_URI), exist_ok=True)

    # Domain: time index 0..n_time-1, lat index 0..n_lat-1, lon index 0..n_lon-1
    # Tile extents picked so a typical regional+yearly query touches ~1-2 tiles
    dom = tiledb.Domain(
        tiledb.Dim(name="time", domain=(0, n_time - 1), tile=4,   dtype=np.int32),
        tiledb.Dim(name="lat",  domain=(0, n_lat  - 1), tile=90,  dtype=np.int32),
        tiledb.Dim(name="lon",  domain=(0, n_lon  - 1), tile=144, dtype=np.int32),
    )
    schema = tiledb.ArraySchema(
        domain=dom,
        sparse=False,
        attrs=[tiledb.Attr(name="co", dtype=np.float32,
                           filters=tiledb.FilterList([tiledb.ZstdFilter(level=5)]))],
        cell_order="row-major",
        tile_order="row-major",
    )
    tiledb.DenseArray.create(TILEDB_URI, schema)
    print(f"[tiledb] created array at {TILEDB_URI} with shape ({n_time},{n_lat},{n_lon})")


def write_one_slice(time_idx, arr):
    with tiledb.DenseArray(TILEDB_URI, mode="w") as A:
        A[time_idx, :, :] = arr.astype(np.float32)


def populate_metadata(rows, lat_coords, lon_coords, units, long_name, fill_val):
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    # Wipe in case we're re-running
    cur.execute("TRUNCATE metadata RESTART IDENTITY;")
    cur.execute("DELETE FROM coord_axis WHERE parameter = %s;", (PARAMETER,))

    # Insert per-timestep rows
    insert_rows = []
    for r in rows:
        insert_rows.append((
            r["time_step"], int(r["time_step"][:4]), int(r["time_step"][4:6]),
            PARAMETER, long_name, units,
            float(lat_coords.min()), float(lat_coords.max()),
            float(lon_coords.min()), float(lon_coords.max()),
            len(lat_coords), len(lon_coords),
            TILEDB_URI, r["legacy_npy"], r["netcdf"],
            float(fill_val) if fill_val is not None else None,
            r["data_min"], r["data_max"], r["data_mean"],
        ))
    execute_values(cur, """
        INSERT INTO metadata
        (time_step, year, month, parameter, parameter_long, units,
         lat_min, lat_max, lon_min, lon_max, n_lat, n_lon,
         tiledb_uri, legacy_npy_path, netcdf_source,
         fill_value, data_min, data_max, data_mean)
        VALUES %s;
    """, insert_rows)

    # Insert coordinate axis lookups
    lat_rows = [(PARAMETER, "lat", i, float(v)) for i, v in enumerate(lat_coords)]
    lon_rows = [(PARAMETER, "lon", i, float(v)) for i, v in enumerate(lon_coords)]
    execute_values(cur,
        "INSERT INTO coord_axis (parameter, axis, idx, value) VALUES %s;",
        lat_rows + lon_rows)

    conn.commit()
    cur.close()
    conn.close()
    print(f"[postgres] inserted {len(insert_rows)} metadata rows, "
          f"{len(lat_rows)+len(lon_rows)} coord rows")


def main():
    files = discover_files()
    if not files:
        raise SystemExit(f"No .nc4 files found in {INPUT_DIR}/")
    print(f"[discover] found {len(files)} NetCDF files")

    # Inspect the first to learn schema
    shape, lat, lon, units, long_name, fill_val = inspect_first(files[0][1])
    n_lat, n_lon = shape
    n_time = len(files)
    print(f"[inspect] grid {n_lat}x{n_lon}, units={units!r}, fill={fill_val}")

    create_tiledb_array(n_time, n_lat, n_lon)

    rows = []
    for time_idx, (ts, path) in enumerate(files):
        ds = xr.open_dataset(path)
        arr = ds[PARAMETER].values.squeeze().astype(np.float32)
        ds.close()

        write_one_slice(time_idx, arr)

        # Compute precomputed stats for cost model + UI
        valid = arr[arr != fill_val] if fill_val is not None else arr
        rows.append(dict(
            time_step=ts,
            netcdf=path,
            legacy_npy=os.path.join(LEGACY_DIR, f"grid_{ts}.npy"),
            data_min=float(valid.min()),
            data_max=float(valid.max()),
            data_mean=float(valid.mean()),
        ))
        print(f"  [{time_idx+1}/{n_time}] wrote slice {ts}")

    populate_metadata(rows, lat, lon, units, long_name, fill_val)
    print("\n[done] migration complete.")
    print(f"  TileDB array: {TILEDB_URI}")
    print(f"  PostgreSQL: pam.metadata + pam.coord_axis populated")


if __name__ == "__main__":
    main()
