"""
Day 3 — Cost Model Calibration Script
======================================
Runs ~50 queries of varying region sizes against the live TileDB array,
measures TileDB read time for each, fits a linear regression:

    cost_ms = α × area_cells + β

where:
    area_cells  = lat_count × lon_count  (cells in the requested region)
    α           = marginal cost per cell (ms/cell)
    β           = base cost (array open + fragment prune + overhead, ms)

Outputs:
    calibration_results.json  — all measurements + fitted α, β, R²
    calibration_results.txt   — human-readable summary for the report
    calibration_plot.png      — scatter plot with regression line (Fig X in report)

Run from EC2:
    cd ~/claude_db_project
    source venv/bin/activate
    python calibrate_cost_model.py

Takes ~3 minutes. Does NOT require PostgreSQL — queries TileDB directly.
The IMS PlanOptimizer will be updated with the fitted α and β afterward.
"""

import time
import json
import gc
import statistics
import numpy as np
import tiledb

# ── Config ──────────────────────────────────────────────────────────────────
TILEDB_URI  = "tiledb_store/pam_co"
N_REPEATS   = 5      # repeats per query for stable median
TIME_IDX    = 0      # always use January (avoids cache bias from alternating months)
OUTPUT_JSON = "calibration_results.json"
OUTPUT_TXT  = "calibration_results.txt"
OUTPUT_PNG  = "calibration_plot.png"

# ── Query grid ───────────────────────────────────────────────────────────────
# 50 queries spanning a wide range of region sizes.
# We vary lat_count and lon_count independently so the regression
# sees both dimensions and confirms area (product) is the right predictor.
#
# lat range: 0..360 (361 cells total)
# lon range: 0..575 (576 cells total)
# We pin the top-left corner at (0,0) and vary width/height.
# This avoids tile-boundary variation confounding the measurement.

QUERY_SPECS = []

lat_sizes = [5, 10, 20, 30, 45, 60, 90, 120, 180, 250, 361]
lon_sizes = [5, 10, 20, 30, 48, 72, 100, 144, 200, 288, 400, 576]

for lat in lat_sizes:
    for lon in lon_sizes:
        if lat * lon <= 361 * 576:          # don't exceed array bounds
            QUERY_SPECS.append((lat, lon))

# Deduplicate and cap at 55 queries
seen = set()
unique_specs = []
for spec in QUERY_SPECS:
    if spec not in seen:
        seen.add(spec)
        unique_specs.append(spec)
        if len(unique_specs) >= 55:
            break

QUERY_SPECS = sorted(unique_specs, key=lambda s: s[0] * s[1])
print(f"Running {len(QUERY_SPECS)} query sizes (from "
      f"{QUERY_SPECS[0][0]*QUERY_SPECS[0][1]:,} to "
      f"{QUERY_SPECS[-1][0]*QUERY_SPECS[-1][1]:,} cells)")


# ── Measurement function ─────────────────────────────────────────────────────
def measure_tiledb_read(lat_count, lon_count, n_repeats=N_REPEATS):
    """
    Open TileDB array, read the specified region, return (median_ms, all_ms).
    One warm-up run first to prime the OS page cache.
    """
    lat_hi = lat_count - 1
    lon_hi = lon_count - 1

    # Warm-up (not timed)
    with tiledb.DenseArray(TILEDB_URI, mode="r") as A:
        _ = A[TIME_IDX, 0:lat_hi+1, 0:lon_hi+1]["co"]

    measurements = []
    for _ in range(n_repeats):
        gc.disable()
        t0 = time.perf_counter()
        with tiledb.DenseArray(TILEDB_URI, mode="r") as A:
            result = A[TIME_IDX, 0:lat_hi+1, 0:lon_hi+1]["co"]
        ms = (time.perf_counter() - t0) * 1000
        gc.enable()
        measurements.append(ms)
        del result

    return statistics.median(measurements), measurements


# ── Run all queries ──────────────────────────────────────────────────────────
print("\nMeasuring...")
print(f"{'lat':>6} {'lon':>6} {'area':>10} {'median_ms':>10} {'min_ms':>8} {'max_ms':>8}")
print("-" * 55)

data_points = []

for i, (lat_count, lon_count) in enumerate(QUERY_SPECS):
    area = lat_count * lon_count
    median_ms, all_ms = measure_tiledb_read(lat_count, lon_count)

    data_points.append({
        "lat_count": lat_count,
        "lon_count": lon_count,
        "area_cells": area,
        "median_ms":  round(median_ms, 4),
        "min_ms":     round(min(all_ms), 4),
        "max_ms":     round(max(all_ms), 4),
        "all_ms":     [round(x, 4) for x in all_ms],
    })

    print(f"{lat_count:>6} {lon_count:>6} {area:>10,} {median_ms:>10.3f} "
          f"{min(all_ms):>8.3f} {max(all_ms):>8.3f}")


# ── Linear regression ────────────────────────────────────────────────────────
# Model: cost_ms = α × area_cells + β
# Fit using numpy least squares (OLS, no intercept constraint).
areas  = np.array([d["area_cells"] for d in data_points], dtype=float)
times  = np.array([d["median_ms"]  for d in data_points], dtype=float)

# Design matrix: [area, 1] for OLS
X = np.column_stack([areas, np.ones_like(areas)])
coeffs, residuals, rank, sv = np.linalg.lstsq(X, times, rcond=None)
alpha, beta = coeffs[0], coeffs[1]

# R² score
times_pred  = alpha * areas + beta
ss_res = np.sum((times - times_pred) ** 2)
ss_tot = np.sum((times - np.mean(times)) ** 2)
r_squared = 1 - ss_res / ss_tot

print(f"\n── Linear regression results ──────────────────────────────────────")
print(f"  α (cost per cell)   = {alpha:.6f} ms/cell")
print(f"  β (base overhead)   = {beta:.4f} ms")
print(f"  R²                  = {r_squared:.4f}")
print(f"\n  Interpretation:")
print(f"  - Base cost to open array + prune fragments: {beta:.1f} ms")
print(f"  - Each additional cell costs ~{alpha*1000:.4f} µs")
print(f"  - India region (56×48=2688 cells): "
      f"estimated {alpha*2688+beta:.1f} ms")
print(f"  - Full grid (361×576=207936 cells): "
      f"estimated {alpha*207936+beta:.1f} ms")
print(f"  - R²={r_squared:.4f} → model explains "
      f"{r_squared*100:.1f}% of variance")


# ── Cost model decision rule ─────────────────────────────────────────────────
# For N sub-queries:
#   sequential_cost = N × (α × area + β)
#   parallel_cost   = max(α × area + β) + thread_overhead
# 
# thread_overhead: measured separately as the cost of spinning up
# ThreadPoolExecutor and joining N futures. Empirically ~3–5 ms for N≤8.
# We use a conservative 5 ms.
#
# Decision: use parallel if N ≥ 2 AND sequential_cost > parallel_cost + 5
# Which simplifies to: use parallel if N ≥ 2 (since sequential is always
# at least N× the single-query cost for equal-sized sub-queries).
# More precisely: parallel threshold = 2 sub-queries.

THREAD_OVERHEAD_MS = 5.0
parallel_threshold_n = 2  # use parallel when n_subqueries >= this

print(f"\n── Plan optimizer decision rule ───────────────────────────────────")
print(f"  sequential_cost(N, area) = N × ({alpha:.6f} × area + {beta:.4f})")
print(f"  parallel_cost(N, area)   = ({alpha:.6f} × area + {beta:.4f}) + {THREAD_OVERHEAD_MS}")
print(f"  Use PARALLEL when N >= {parallel_threshold_n}")
print(f"  (because for N=2: sequential={2*(alpha*2688+beta):.1f}ms, "
      f"parallel={alpha*2688+beta+THREAD_OVERHEAD_MS:.1f}ms)")


# ── Save results ─────────────────────────────────────────────────────────────
results = {
    "model": {
        "alpha_ms_per_cell": round(alpha, 8),
        "beta_ms":           round(beta, 4),
        "r_squared":         round(r_squared, 6),
        "thread_overhead_ms": THREAD_OVERHEAD_MS,
        "parallel_threshold_n": parallel_threshold_n,
        "formula": "cost_ms = alpha * area_cells + beta",
        "n_calibration_points": len(data_points),
    },
    "data_points": data_points,
}

with open(OUTPUT_JSON, "w") as f:
    json.dump(results, f, indent=2)

with open(OUTPUT_TXT, "w") as f:
    f.write("PAM Day 3 — Cost Model Calibration Results\n")
    f.write("=" * 50 + "\n\n")
    f.write(f"Model: cost_ms = α × area_cells + β\n\n")
    f.write(f"  α = {alpha:.6f} ms/cell\n")
    f.write(f"  β = {beta:.4f} ms\n")
    f.write(f"  R² = {r_squared:.4f}\n\n")
    f.write(f"Calibration points: {len(data_points)}\n\n")
    f.write("Key predictions:\n")
    f.write(f"  Small region   (5×5=25 cells):     {alpha*25+beta:.2f} ms\n")
    f.write(f"  Delhi bbox     (10×10=100 cells):   {alpha*100+beta:.2f} ms\n")
    f.write(f"  India bbox     (56×48=2688 cells):  {alpha*2688+beta:.2f} ms\n")
    f.write(f"  Half globe     (180×288=51840):     {alpha*51840+beta:.2f} ms\n")
    f.write(f"  Full grid      (361×576=207936):    {alpha*207936+beta:.2f} ms\n\n")
    f.write("Decision rule:\n")
    f.write(f"  Use PARALLEL when n_subqueries >= {parallel_threshold_n}\n\n")
    f.write("Raw data:\n")
    f.write(f"{'lat':>6} {'lon':>6} {'area':>10} {'median_ms':>10}\n")
    f.write("-" * 36 + "\n")
    for d in data_points:
        f.write(f"{d['lat_count']:>6} {d['lon_count']:>6} "
                f"{d['area_cells']:>10,} {d['median_ms']:>10.3f}\n")

print(f"\nSaved: {OUTPUT_JSON}")
print(f"Saved: {OUTPUT_TXT}")


# ── Plot (optional — skip gracefully if matplotlib not available) ─────────────
try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.scatter(areas / 1000, times,
               color="#2c7a2c", alpha=0.7, s=40, label="Measured (median)")

    x_line = np.linspace(0, areas.max(), 300)
    y_line = alpha * x_line + beta
    ax.plot(x_line / 1000, y_line,
            color="#c0392b", linewidth=2,
            label=f"Fit: {alpha:.4f}·area + {beta:.2f}  (R²={r_squared:.3f})")

    # Annotate key regions
    for label, cells in [("India bbox\n(56×48)", 2688),
                          ("Full grid\n(361×576)", 207936)]:
        ax.annotate(label,
                    xy=(cells / 1000, alpha * cells + beta),
                    xytext=(cells / 1000 + 15, alpha * cells + beta + 1),
                    fontsize=8, color="#333",
                    arrowprops=dict(arrowstyle="->", color="#999", lw=0.8))

    ax.set_xlabel("Region size (thousand cells)", fontsize=11)
    ax.set_ylabel("TileDB read time (ms, median of 5 runs)", fontsize=11)
    ax.set_title("PAM Cost Model Calibration\n"
                 "TileDB read time vs region size (warm cache, single month)",
                 fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x:.0f}k"))

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches="tight")
    print(f"Saved: {OUTPUT_PNG}")
    plt.close()

except ImportError:
    print("matplotlib not available — skipping plot (install with: pip install matplotlib)")

print("\nDone. Next step:")
print("  Copy calibration_results.json back here and say 'update cost model'")
print("  This will update PlanOptimizer with the fitted α and β.")
