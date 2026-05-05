"""
TaskAnalyzer — classifies the incoming query and resolves user-friendly
inputs (degrees, time strings) into engine-friendly inputs (indices).

Day 1: a working implementation that handles the three patterns the UI emits:
    - single-time spatial slice
    - time-range spatial slice  (Day 2 will wire this into the UI)
    - aggregation queries       (Day 4)

Day 2 will replace the dict-based `query` with a proper parsed AST.
"""
from typing import Dict, Any


class TaskAnalyzer:
    def __init__(self, metadata_manager):
        self.meta = metadata_manager

    def analyze(self, query: Dict[str, Any]) -> Dict[str, Any]:
        param = query.get("parameter", "COCL")
        time_spec = query["time"]
        region = query.get("region")

        # Time: single step vs range
        if isinstance(time_spec, str):
            time_steps = [time_spec]
            qtype = "single_time"
        else:
            ts_from = time_spec.get("from_") or time_spec["from"]; ts_to = time_spec["to"]
            all_ts = self.meta.all_time_steps(param)
            time_steps = [t for t in all_ts if ts_from <= t <= ts_to]
            qtype = "time_range"

        # Region: degrees -> array indices via coord_axis (the metadata DB doing real work)
        if region is None:
            lat_idx = lon_idx = None
        else:
            lat_lo, lat_hi = sorted(region["lat"])
            lon_lo, lon_hi = sorted(region["lon"])
            lat_idx = self.meta.degrees_to_indices(param, "lat", lat_lo, lat_hi)
            lon_idx = self.meta.degrees_to_indices(param, "lon", lon_lo, lon_hi)

        return {
            "type":       qtype,
            "parameter":  param,
            "time_steps": time_steps,
            "region_deg": region,
            "lat_idx":    lat_idx,            # (lo, hi) inclusive or None
            "lon_idx":    lon_idx,
            "aggs":       query.get("aggregations", []),
        }
