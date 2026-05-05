"""
Day 4: fair head-to-head benchmark.

Architectures
  pure_pg : flattened relational grid_flat (psycopg2, in-process)
  v2      : TileDB + PostgreSQL + IMS (qi.execute(), in-process — no HTTP)

Both measured at the library level: no FastAPI, no HTTP, no JSON serialization.
This is the same methodology used by the reference paper (He et al. 2024).

Workload (6 queries × 10 warm runs each).
Correctness: pure_pg and v2 must return the same scientific mean (tol 1e-6).
"""
import csv, os, statistics, sys, time
from typing import Callable, Dict, Any, List, Tuple

import psycopg2

sys.path.insert(0, os.path.expanduser("~/claude_db_project"))
from ims.query_interface import QueryInterface

PG = dict(dbname="pam", user="postgres", password="postgres", host="localhost")
N_RUNS = 10
PARAM  = "COCL"


def degrees_to_indices(conn, axis, lo, hi):
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(idx), MAX(idx) FROM coord_axis "
        "WHERE parameter=%s AND axis=%s AND value BETWEEN %s AND %s",
        (PARAM, axis, lo, hi))
    a, b = cur.fetchone(); cur.close()
    return int(a), int(b)


def build_queries(conn):
    india_lat = degrees_to_indices(conn, "lat",  8.0,  35.0)
    india_lon = degrees_to_indices(conn, "lon", 68.0,  97.0)
    asia_lat  = degrees_to_indices(conn, "lat",  0.0,  60.0)
    asia_lon  = degrees_to_indices(conn, "lon", 60.0, 150.0)
    pt_lat    = degrees_to_indices(conn, "lat", 22.0, 22.5)
    pt_lon    = degrees_to_indices(conn, "lon", 78.0, 78.5)
    return [
        dict(id="Q1_point", label="single cell, single time",
             ims=dict(parameter=PARAM, time="201901",
                      region=dict(lat=[22.0,22.5], lon=[78.0,78.5])),
             lat_idx=pt_lat, lon_idx=pt_lon, time_steps=["201901"]),
        dict(id="Q2_small_region", label="India, single month",
             ims=dict(parameter=PARAM, time="201901",
                      region=dict(lat=[8.0,35.0], lon=[68.0,97.0])),
             lat_idx=india_lat, lon_idx=india_lon, time_steps=["201901"]),
        dict(id="Q3_large_region", label="Asia, single month",
             ims=dict(parameter=PARAM, time="201901",
                      region=dict(lat=[0.0,60.0], lon=[60.0,150.0])),
             lat_idx=asia_lat, lon_idx=asia_lon, time_steps=["201901"]),
        dict(id="Q4_range_region", label="India, 6 months",
             ims=dict(parameter=PARAM, time={"from":"201901","to":"201906"},
                      region=dict(lat=[8.0,35.0], lon=[68.0,97.0])),
             lat_idx=india_lat, lon_idx=india_lon,
             time_steps=["201901","201902","201903","201904","201905","201906"]),
        dict(id="Q5_global", label="full grid, single month",
             ims=dict(parameter=PARAM, time="201901"),
             lat_idx=(0,360), lon_idx=(0,575), time_steps=["201901"]),
        dict(id="Q6_timeseries_pt", label="single cell, all 16 months",
             ims=dict(parameter=PARAM, time={"from":"201901","to":"202004"},
                      region=dict(lat=[22.0,22.5], lon=[78.0,78.5])),
             lat_idx=pt_lat, lon_idx=pt_lon,
             time_steps=["201901","201902","201903","201904","201905","201906",
                         "201907","201908","201909","201910","201911","201912",
                         "202001","202002","202003","202004"]),
    ]


def run_pure_pg(q):
    """One SQL aggregate over grid_flat with all filters in WHERE."""
    la_lo, la_hi = q["lat_idx"]; lo_lo, lo_hi = q["lon_idx"]
    t0 = time.perf_counter()
    conn = psycopg2.connect(**PG); cur = conn.cursor()
    if len(q["time_steps"]) == 1:
        cur.execute("""
            SELECT AVG(value) FROM grid_flat
            WHERE parameter=%s AND time_step=%s
              AND lat_idx BETWEEN %s AND %s
              AND lon_idx BETWEEN %s AND %s
              AND value < 1e10
        """, (PARAM, q["time_steps"][0], la_lo, la_hi, lo_lo, lo_hi))
    else:
        cur.execute("""
            SELECT AVG(value) FROM grid_flat
            WHERE parameter=%s AND time_step = ANY(%s)
              AND lat_idx BETWEEN %s AND %s
              AND lon_idx BETWEEN %s AND %s
              AND value < 1e10
        """, (PARAM, q["time_steps"], la_lo, la_hi, lo_lo, lo_hi))
    (mean,) = cur.fetchone()
    cur.close(); conn.close()
    return float(mean), (time.perf_counter() - t0) * 1000


def run_v2_inproc(q, qi):
    """Library-level v2 — call QueryInterface.execute() directly. No HTTP."""
    t0 = time.perf_counter()
    result = qi.execute(q["ims"])
    elapsed = (time.perf_counter() - t0) * 1000
    return float(result["stats"]["mean"]), elapsed


def time_runs(fn, q, n):
    means, mss = [], []
    for _ in range(n):
        m, ms = fn(q); means.append(m); mss.append(ms)
    return means[-1], mss


def summarize(label, mss):
    return dict(arch=label,
                median_ms=round(statistics.median(mss), 2),
                min_ms=round(min(mss), 2),
                max_ms=round(max(mss), 2),
                mean_ms=round(statistics.mean(mss), 2))


def main():
    print("=" * 70)
    print("PAM Day 4 fair benchmark — pure-PG vs v2 (both in-process)")
    print("=" * 70)

    # Storage comparison up front
    conn = psycopg2.connect(**PG); cur = conn.cursor()
    cur.execute("SELECT pg_size_pretty(pg_total_relation_size('grid_flat'));")
    (pg_size,) = cur.fetchone()
    cur.close()

    # TileDB on-disk size via du
    import subprocess
    tdb_path = os.path.expanduser("~/claude_db_project/tiledb_store/pam_co")
    tdb_size = subprocess.check_output(["du","-sh", tdb_path]).split()[0].decode()

    print(f"\nStorage: grid_flat = {pg_size}, TileDB = {tdb_size}")

    queries = build_queries(conn)
    qi = QueryInterface()
    conn.close()

    rows = []
    for q in queries:
        print(f"\n--- {q['id']}: {q['label']} ---")
        results = {}
        for arch_label, fn in [
            ("pure_pg", run_pure_pg),
            ("v2",      lambda qq: run_v2_inproc(qq, qi)),
        ]:
            try:
                fn(q)  # warmup, not counted
            except Exception as e:
                print(f"  {arch_label}: WARMUP FAILED ({e})")
                results[arch_label] = None; continue
            mean_val, mss = time_runs(fn, q, N_RUNS)
            stats = summarize(arch_label, mss)
            stats["mean_value"] = round(mean_val, 9)
            results[arch_label] = stats
            print(f"  {arch_label:8s}  median={stats['median_ms']:7.2f} ms  "
                  f"min={stats['min_ms']:6.2f}  max={stats['max_ms']:6.2f}  "
                  f"mean_value={stats['mean_value']}")

        valid = [r for r in results.values() if r is not None]
        if len(valid) >= 2:
            vals = [r["mean_value"] for r in valid]
            spread = max(vals) - min(vals)
            ok = spread < 1e-6
            print(f"  correctness: spread={spread:.2e} {'✓ OK' if ok else '✗ MISMATCH'}")
            speedup = (results["pure_pg"]["median_ms"] /
                       results["v2"]["median_ms"]) if results.get("v2") else None
            if speedup:
                tag = f"{speedup:.2f}x" + (" v2 faster" if speedup > 1
                                            else " pure_pg faster")
                print(f"  speedup:     {tag}")
        else:
            ok = False; spread = None

        for arch_label, stats in results.items():
            if stats is None: continue
            rows.append(dict(
                query_id=q["id"], query_label=q["label"], arch=arch_label,
                median_ms=stats["median_ms"], min_ms=stats["min_ms"],
                max_ms=stats["max_ms"], mean_ms=stats["mean_ms"],
                mean_value=stats["mean_value"],
                correctness_spread=(round(spread,9) if spread is not None else None),
                correctness_ok=ok))

    out = os.path.expanduser("~/claude_db_project/bench/results_fair.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "query_id","query_label","arch","median_ms","min_ms","max_ms",
            "mean_ms","mean_value","correctness_spread","correctness_ok"])
        w.writeheader(); w.writerows(rows)
    print(f"\n[OK] Results -> {out}")
    print(f"     Storage: grid_flat = {pg_size}, TileDB = {tdb_size}")


if __name__ == "__main__":
    main()
