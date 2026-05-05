"""
Day 3 additions to api.py
==========================
Add these three things to ~/claude_db_project/api.py:

1. POST /ims/explain    — returns plan + cost estimate, no execution
2. query_log population — write a row after every /ims/query call
3. Updated PlanOptimizer import — use the calibrated version

INSTRUCTIONS:
    On EC2, copy plan_optimizer_v2.py to ~/claude_db_project/ims/plan_optimizer.py
    Then apply the diffs below to ~/claude_db_project/api.py.

    Simplest approach: replace the entire api.py with this file.
"""

import os
import json
import time
import psycopg2
import tiledb
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
from typing import Optional, List, Union
from ims import QueryInterface

app = FastAPI(title="PAM v2 API", version="2.0.0")

# ── Shared QueryInterface (initialises PlanOptimizer with calibration) ────────
qi = QueryInterface()

# ── Pydantic models ───────────────────────────────────────────────────────────
class TimeRange(BaseModel):
    from_: str
    to: str

    class Config:
        fields = {"from_": "from"}

    @validator("from_", "to")
    def validate_yyyymm(cls, v):
        if not (len(v) == 6 and v.isdigit()):
            raise ValueError(f"time must be YYYYMM, got: {v}")
        return v

class Region(BaseModel):
    lat: List[float]
    lon: List[float]

    @validator("lat", "lon")
    def validate_two_values(cls, v, field):
        if len(v) != 2:
            raise ValueError(f"{field.name} must have exactly 2 values")
        return v

class QueryBody(BaseModel):
    parameter: str = "COCL"
    time: Union[str, TimeRange]
    region: Optional[Region] = None
    aggregations: Optional[List[str]] = None

# ── PostgreSQL connection helper ──────────────────────────────────────────────
PG_CONN = dict(
    dbname="pam", user="postgres",
    password="postgres", host="localhost"
)

def write_query_log(query_json, plan_json, pg_time_ms,
                    array_time_ms, total_time_ms,
                    result_shape, n_files_pruned):
    """Write one row to query_log. Fails silently so a log error
    never breaks a real query response."""
    try:
        conn = psycopg2.connect(**PG_CONN)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO query_log
                (query_json, plan_json, pg_time_ms, array_time_ms,
                 total_time_ms, result_shape, n_files_pruned)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            json.dumps(query_json),
            json.dumps(plan_json),
            pg_time_ms,
            array_time_ms,
            total_time_ms,
            str(result_shape),
            n_files_pruned,
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[query_log] write failed (non-fatal): {e}")


# ── Legacy v1 endpoint (unchanged) ───────────────────────────────────────────
@app.get("/query")
async def legacy_query(time: str, lat_min: int, lat_max: int,
                       lon_min: int, lon_max: int):
    """v1 compatible endpoint. Kept for backward compatibility."""
    try:
        with tiledb.DenseArray("tiledb_store/pam_co", mode="r") as A:
            all_steps = sorted(qi.meta_manager.get_all_time_steps())
            if time not in all_steps:
                raise HTTPException(404, f"Unknown time step: {time}")
            t_idx = all_steps.index(time)
            data  = A[t_idx, lat_min:lat_max+1, lon_min:lon_max+1]["co"]
        arr = np.where(data < 1e10, data, np.nan)
        return {
            "mean": float(np.nanmean(arr)),
            "max":  float(np.nanmax(arr)),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── v2 health check ──────────────────────────────────────────────────────────
@app.get("/ims/health")
async def health():
    steps = qi.meta_manager.get_all_time_steps()
    return {
        "status": "ok",
        "time_steps_loaded": len(steps),
        "version": "2.0.0",
    }


# ── v2 time steps ────────────────────────────────────────────────────────────
@app.get("/ims/time_steps")
async def time_steps():
    return {"time_steps": sorted(qi.meta_manager.get_all_time_steps())}


# ── v2 main query endpoint ───────────────────────────────────────────────────
@app.post("/ims/query")
async def ims_query(body: QueryBody):
    t_total_start = time.perf_counter()
    query_dict    = body.dict()

    try:
        result = qi.execute(query_dict)
    except Exception as e:
        raise HTTPException(500, str(e))

    total_ms = (time.perf_counter() - t_total_start) * 1000

    # ── Write to query_log ────────────────────────────────────────────────
    trace = result.get("_trace", {})
    plan  = trace.get("plan", {})

    # Extract timing breakdown from trace if available
    pg_time_ms    = trace.get("pg_time_ms", 0.0)
    array_time_ms = trace.get("array_time_ms", 0.0)
    n_pruned      = plan.get("n_pruned", 0)

    write_query_log(
        query_json     = query_dict,
        plan_json      = plan,
        pg_time_ms     = round(pg_time_ms, 3),
        array_time_ms  = round(array_time_ms, 3),
        total_time_ms  = round(total_ms, 3),
        result_shape   = result.get("shape", []),
        n_files_pruned = n_pruned,
    )

    return result


# ── NEW: v2 explain endpoint ─────────────────────────────────────────────────
@app.post("/ims/explain")
async def ims_explain(body: QueryBody):
    """
    Returns the IMS query plan and cost estimate WITHOUT executing the query.
    Analogous to SQL's EXPLAIN statement.

    Useful for:
    - Previewing whether a query will run sequentially or in parallel
    - Understanding the cost model prediction before committing to a long query
    - The Streamlit "Explain query" button

    Response includes:
        strategy         : "sequential" | "parallel"
        n_subqueries     : how many TileDB reads will be issued
        estimated_ms     : predicted wall-clock time
        cost_model       : α, β, R², source
        explanation      : human-readable plain-English breakdown
        subqueries       : per-step cost breakdown
    """
    query_dict = body.dict()
    try:
        plan = qi.explain(query_dict)
    except Exception as e:
        raise HTTPException(500, str(e))
    return plan
