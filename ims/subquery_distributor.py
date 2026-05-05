"""
SubqueryDistributor — executes the plan against the array engine (TileDB).

Day 1: real implementation of both sequential and parallel execution paths.
Day 3 will add result streaming / chunking for very large queries.
"""
import time
import numpy as np
import tiledb
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Tuple


def _run_one(sub: Dict[str, Any]) -> Tuple[str, np.ndarray, float]:
    """Execute a single TileDB subquery; return (time_step, slice, ms)."""
    t0 = time.perf_counter()
    with tiledb.DenseArray(sub["tiledb_uri"], mode="r") as A:
        if sub["lat_slice"] is None:
            data = A[sub["time_idx"], :, :]["co"]
        else:
            lat_lo, lat_hi = sub["lat_slice"]
            lon_lo, lon_hi = sub["lon_slice"]
            # TileDB slicing is INCLUSIVE on both ends -- different from NumPy
            data = A[sub["time_idx"], lat_lo:lat_hi+1, lon_lo:lon_hi+1]["co"]
    return sub["time_step"], np.asarray(data), (time.perf_counter() - t0) * 1000


class SubqueryDistributor:
    def distribute(self, plan: Dict[str, Any]):
        subs = plan["subqueries"]
        timings = []
        results = []

        if plan["strategy"] == "parallel" and len(subs) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(subs))) as ex:
                for ts, arr, ms in ex.map(_run_one, subs):
                    results.append((ts, arr))
                    timings.append({"time_step": ts, "ms": round(ms, 2)})
        else:
            for sub in subs:
                ts, arr, ms = _run_one(sub)
                results.append((ts, arr))
                timings.append({"time_step": ts, "ms": round(ms, 2)})

        return results, timings
