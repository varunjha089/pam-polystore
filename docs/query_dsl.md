# PAM Unified Query DSL (v2)

The PAM v2 backend exposes a single query endpoint that accepts a JSON body
and returns the result plus an execution trace. This document defines the
DSL formally and gives canonical examples.

> Endpoint: `POST /ims/query` on `http://<host>:8001`

## 1. Why a JSON DSL and not raw SQL?

In a polystore, the user's query is not a SQL statement. It must be split
across two engines (PostgreSQL for metadata, TileDB for arrays) by the IMS,
and the IMS needs a structured representation it can analyze, plan, and
optimize against. SQL would force one engine to be the "primary"; JSON
keeps the front-end neutral.

This mirrors the design choice in BigDAWG (cross-island queries) and in
the He et al. (2024) PAM paper, where queries are decomposed into
sub-queries on different domains (`G`, `T`, `R`).

## 2. Grammar

```
Query        := { parameter, time, region?, aggregations?, options? }

parameter    := <string>             # currently 'COCL'; Day 4 adds COSC, COEM, TO3
time         := <TimeStep> | <TimeRange>
TimeStep     := <string YYYYMM>      # e.g. '201901'
TimeRange    := { from: <YYYYMM>, to: <YYYYMM> }
region       := { lat: [<float>, <float>], lon: [<float>, <float>] } | null
                                     # both in DEGREES, lat ∈ [-90, 90], lon ∈ [-180, 180]
aggregations := list of <string>     # any of: 'mean', 'max', 'min', 'std'
options      := { strategy?: 'sequential'|'parallel'|'auto',
                  cache?:    boolean }    # Day 4 wires cache; today 'auto' is implied
```

## 3. Response shape

```json
{
  "shape":      [<int>, ...],          // numpy shape of returned data
  "data":       [...]  ,               // nested list -> reshape to `shape`
  "stats":      { mean, max, min, std, count },
  "time_steps": ["201901", ...],        // list of T steps actually returned
  "units":      "kg m-2",
  "_trace": {
    "stages": [
      { "stage": "analyze",     "task_type": "single_time" | "time_range" },
      { "stage": "plan",        "strategy": "...", "n_subqueries": N, "n_pruned": M },
      { "stage": "distribute",  "timings_ms": [ {time_step, ms}, ... ] }
    ],
    "total_ms": <float>
  }
}
```

The `_trace` field is what the Streamlit "Query Plan" tab displays and
what gets persisted to the `query_log` PostgreSQL table for benchmarks.

## 4. Five canonical examples

### Example A — Single time step, full global grid

```json
{ "parameter": "COCL", "time": "201901" }
```

Returns shape `[361, 576]`. Used for "show me the whole world this month."
Strategy: sequential (one sub-query).

### Example B — Single time step, regional slice (degrees)

```json
{
  "parameter": "COCL",
  "time": "201901",
  "region": { "lat": [8, 35], "lon": [68, 97] }
}
```

Returns shape `[55, 47]` (for India-shaped bbox at 0.5°×0.625° resolution).
The IMS resolves the degree bounds to array indices via the `coord_axis`
table BEFORE any TileDB read happens.

### Example C — Time range, regional, parallel execution

```json
{
  "parameter": "COCL",
  "time": { "from": "201901", "to": "201906" },
  "region": { "lat": [8, 35], "lon": [68, 97] }
}
```

Returns shape `[6, 55, 47]`. The PlanOptimizer picks `strategy: parallel`
because the sub-query count crosses the threshold. Sub-queries fan out to
the TileDB array via a thread pool.

### Example D — Aggregation only (no raw data)

```json
{
  "parameter": "COCL",
  "time": "201901",
  "region": { "lat": [8, 35], "lon": [68, 97] },
  "aggregations": ["mean", "max"]
}
```

`stats` always populated; aggregations field reserved for Day 4 cost
optimization (so the planner knows it can skip materializing the full
array if only a scalar is needed).

### Example E — Whole world, all time, statistics only

```json
{
  "parameter": "COCL",
  "time": { "from": "201901", "to": "202004" },
  "region": null,
  "aggregations": ["mean", "max", "std"]
}
```

Returns shape `[16, 361, 576]`. Used as the most-expensive workload in the
Day 5 benchmark.

## 5. Errors

| HTTP | Meaning                                                             |
|------|---------------------------------------------------------------------|
| 400  | Validation error (e.g. `time` not YYYYMM, lat outside [-90, 90])     |
| 404  | Time step or parameter unknown                                       |
| 500  | Internal IMS error — check `~/claude_db_project/logs/api.log`        |

## 6. What is intentionally NOT in the DSL today

- **Spatial joins across parameters** (e.g. `CO * temperature`). Day 4.
- **Predicate pushdown on values** (e.g. "cells where CO > 0.0007").
  Possible via TileDB query conditions; deferred.
- **GROUP BY time** for downsampling (e.g. quarterly means from monthly).
  Easy to add post-hoc in the Accumulator; not in v0.
- **Authentication / per-user quotas**. This is a single-user demo
  system; a real deployment would put this behind an auth proxy.
