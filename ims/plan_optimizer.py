import json, math, os

ALPHA_MS_PER_CELL  = 0.000068
BETA_MS            = 3.2323
R_SQUARED          = 0.6092
THREAD_OVERHEAD_MS = 5.0
PARALLEL_THRESHOLD = 2
TILE_LAT           = 90
TILE_LON           = 144

class PlanOptimizer:

    def __init__(self, *args, **kwargs):
        path = "calibration_results.json"
        if isinstance(path, str) and os.path.exists(path):
            try:
                cal = json.load(open(path))["model"]
                self.alpha  = cal["alpha_ms_per_cell"]
                self.beta   = cal["beta_ms"]
                self.r_sq   = cal["r_squared"]
                self.source = "calibrated R2={:.4f}".format(cal["r_squared"])
                print("[PlanOptimizer] calibrated alpha={:.6f} beta={:.4f}".format(self.alpha, self.beta))
                return
            except Exception as e:
                print("[PlanOptimizer] error: {}".format(e))
        self.alpha  = ALPHA_MS_PER_CELL
        self.beta   = BETA_MS
        self.r_sq   = R_SQUARED
        self.source = "hardcoded 30-Apr-2026"
        print("[PlanOptimizer] defaults alpha={:.6f} beta={:.4f}".format(self.alpha, self.beta))

    def estimate_cost(self, lat_count, lon_count):
        area    = lat_count * lon_count
        cost    = max(0.5, self.alpha * area + self.beta)
        n_tiles = math.ceil(lat_count / TILE_LAT) * math.ceil(lon_count / TILE_LON)
        return {"area_cells": area, "n_tiles": n_tiles, "cost_ms": round(cost, 3)}

    def build_plan(self, meta):
        time_steps   = meta["time_steps"]
        time_indices = meta["time_indices"]
        lat_lo, lat_hi = meta["lat_slice"]
        lon_lo, lon_hi = meta["lon_slice"]
        tiledb_uri   = meta["tiledb_uri"]
        fill_value   = meta.get("fill_value", 1e15)
        lat_count = lat_hi - lat_lo + 1
        lon_count = lon_hi - lon_lo + 1
        n         = len(time_steps)
        ci        = self.estimate_cost(lat_count, lon_count)
        csq       = ci["cost_ms"]
        seq       = n * csq
        par       = csq + THREAD_OVERHEAD_MS
        strategy  = "parallel" if n >= PARALLEL_THRESHOLD else "sequential"
        estimated = par if strategy == "parallel" else seq
        subqueries = [
            {"time_step": ts, "time_idx": ti,
             "tiledb_uri": tiledb_uri,
             "lat_slice": (lat_lo, lat_hi),
             "lon_slice": (lon_lo, lon_hi),
             "fill_value": fill_value,
             "estimated_ms": csq}
            for ts, ti in zip(time_steps, time_indices)
        ]
        return {
            "strategy": strategy,
            "n_subqueries": n,
            "n_pruned": 0,
            "area_cells": ci["area_cells"],
            "n_tiles_per_subquery": ci["n_tiles"],
            "cost_per_subquery_ms": csq,
            "sequential_cost_ms": round(seq, 3),
            "parallel_cost_ms":   round(par, 3),
            "estimated_ms":       round(estimated, 3),
            "cost_model": {
                "alpha": self.alpha,
                "beta":  self.beta,
                "r_sq":  self.r_sq,
                "source": self.source,
                "formula": "cost_ms = alpha * area_cells + beta",
                "note": "R2={:.4f}: tile-load dominated (tile={} cells/tile)".format(
                    self.r_sq, TILE_LAT * TILE_LON),
            },
            "subqueries": subqueries,
        }

    def explain(self, meta):
        plan = self.build_plan(meta)
        plan["explanation"] = (
            "Region: {:,} cells, {} tile(s). "
            "Per-subquery: {:.2f} ms. "
            "N={}: sequential={:.1f} ms, parallel={:.1f} ms. "
            "Strategy: {}.".format(
                plan["area_cells"],
                plan["n_tiles_per_subquery"],
                plan["cost_per_subquery_ms"],
                plan["n_subqueries"],
                plan["sequential_cost_ms"],
                plan["parallel_cost_ms"],
                plan["strategy"].upper()
            )
        )
        return plan

    def plan(self, task):
        """Called by QueryInterface.execute(). task comes from TaskAnalyzer."""
        # task keys: type, parameter, time_steps, region_deg, lat_idx, lon_idx, aggs
        lat_idx = task.get("lat_idx") or (0, 360)
        lon_idx = task.get("lon_idx") or (0, 575)
        time_steps = task.get("time_steps", [])

        # time_indices: position of each time_step in the sorted list
        try:
            import psycopg2
            conn = psycopg2.connect(dbname="pam", user="postgres",
                                    password="postgres", host="localhost")
            cur = conn.cursor()
            cur.execute("SELECT time_step FROM metadata WHERE parameter=%s ORDER BY time_step",
                        (task.get("parameter", "COCL"),))
            all_steps = [r[0] for r in cur.fetchall()]
            cur.close(); conn.close()
            time_indices = [all_steps.index(ts) for ts in time_steps if ts in all_steps]
        except Exception:
            time_indices = list(range(len(time_steps)))

        meta = {
            "time_steps":   time_steps,
            "time_indices": time_indices,
            "lat_slice":    lat_idx,
            "lon_slice":    lon_idx,
            "tiledb_uri":   "tiledb_store/pam_co",
            "fill_value":   1e15,
        }
        return self.build_plan(meta)

