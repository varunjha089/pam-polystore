"""Day 4: load grid_flat from the TileDB array using COPY."""
import io, os, time
import psycopg2, tiledb

PG = dict(dbname="pam", user="postgres", password="postgres", host="localhost")
TDB_URI = os.path.expanduser("~/claude_db_project/tiledb_store/pam_co")
PARAMETER = "COCL"
TIME_STEPS = ["201901","201902","201903","201904","201905","201906",
              "201907","201908","201909","201910","201911","201912",
              "202001","202002","202003","202004"]

def main():
    t0 = time.perf_counter()
    print(f"[load_grid_flat] reading {TDB_URI} ...", flush=True)
    with tiledb.DenseArray(TDB_URI, mode="r") as A:
        full = A[:, :, :]["co"]
    print(f"[load_grid_flat] loaded shape={full.shape} in {time.perf_counter()-t0:.1f}s", flush=True)

    n_time, n_lat, n_lon = full.shape
    print(f"[load_grid_flat] will COPY {n_time*n_lat*n_lon:,} rows", flush=True)

    conn = psycopg2.connect(**PG); cur = conn.cursor()
    cur.execute("TRUNCATE grid_flat;"); conn.commit()

    t1 = time.perf_counter()
    buf = io.StringIO(); write = buf.write
    for ti in range(n_time):
        ts = TIME_STEPS[ti]; plane = full[ti]
        for la in range(n_lat):
            row = plane[la]
            for lo in range(n_lon):
                write(f"{ts}\t{PARAMETER}\t{la}\t{lo}\t{float(row[lo]):.6e}\n")
    print(f"[load_grid_flat] built buffer ({buf.tell()/1e6:.1f} MB) in {time.perf_counter()-t1:.1f}s", flush=True)

    t2 = time.perf_counter(); buf.seek(0)
    cur.copy_expert(
        "COPY grid_flat (time_step,parameter,lat_idx,lon_idx,value) FROM STDIN WITH (FORMAT text)",
        buf)
    conn.commit()
    print(f"[load_grid_flat] COPY in {time.perf_counter()-t2:.1f}s", flush=True)

    print("[load_grid_flat] building indexes ...", flush=True)
    t3 = time.perf_counter()
    cur.execute("""
        CREATE INDEX idx_grid_flat_time_param ON grid_flat (time_step, parameter);
        CREATE INDEX idx_grid_flat_latlon     ON grid_flat (lat_idx, lon_idx);
        CREATE INDEX idx_grid_flat_full       ON grid_flat (parameter, time_step, lat_idx, lon_idx);
        ANALYZE grid_flat;
    """)
    conn.commit()
    print(f"[load_grid_flat] indexes in {time.perf_counter()-t3:.1f}s", flush=True)

    cur.execute("SELECT COUNT(*) FROM grid_flat;"); (n,) = cur.fetchone()
    cur.execute("SELECT pg_size_pretty(pg_total_relation_size('grid_flat'));"); (size,) = cur.fetchone()
    cur.close(); conn.close()
    print(f"[load_grid_flat] DONE: {n:,} rows, {size} on disk, total {time.perf_counter()-t0:.1f}s", flush=True)

if __name__ == "__main__":
    main()
