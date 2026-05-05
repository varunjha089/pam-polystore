"""
Accumulator — merges per-subquery slices into a single result and computes
any aggregations the user asked for.
"""
import numpy as np
from typing import List, Tuple, Dict, Any


class Accumulator:
    def merge(self, results: List[Tuple[str, np.ndarray]],
              task: Dict[str, Any], original_query: Dict[str, Any]) -> Dict[str, Any]:
        if not results:
            return {"shape": [], "data": [], "stats": {}, "time_steps": []}

        # Stack along a new time axis (results are already in time order from the optimizer)
        results.sort(key=lambda r: r[0])
        time_steps = [r[0] for r in results]
        stacked = np.stack([r[1] for r in results], axis=0)

        # Single-time queries: drop the leading axis to keep the legacy UI happy
        if task["type"] == "single_time" and stacked.shape[0] == 1:
            payload = stacked[0]
        else:
            payload = stacked

        # Always-on stats (cheap and useful for the UI's Statistics panel)
        # MERRA-2 fill values are huge sentinels; mask them.
        mask = np.isfinite(payload) & (payload < 1e10)
        valid = payload[mask] if mask.any() else payload

        stats = {
            "mean": float(valid.mean()) if valid.size else None,
            "max":  float(valid.max())  if valid.size else None,
            "min":  float(valid.min())  if valid.size else None,
            "std":  float(valid.std())  if valid.size else None,
            "count": int(valid.size),
        }

        return {
            "shape": list(payload.shape),
            "data": payload.tolist(),            # numpy array; FastAPI layer serializes
            "stats": stats,
            "time_steps": time_steps,
            "units": "kg kg-1",
        }
