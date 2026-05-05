# PAM Polystore

**Polystore for Atmospheric Modelling** — an M.Tech Advanced Databases project
that combines **PostgreSQL 16** (relational catalogue) and **TileDB** (dense array
store) to serve MERRA-2 CO column-loading climate data through a six-module
Information Management System (IMS).

> Storage win: TileDB array **28× smaller** than an equivalent PostgreSQL flat table (11 MB vs 314 MB).
> Query win: **2.31× faster** than pure-PG on global spatial aggregates.
> Correctness: **0.00 spread** across all 60 paired benchmark runs.

---

## Table of Contents

1. [Architecture overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Setup](#3-setup)
4. [Load data](#4-load-data)
5. [Run the services](#5-run-the-services)
6. [API reference](#6-api-reference)
7. [Run the benchmark](#7-run-the-benchmark)
8. [Project layout](#8-project-layout)
9. [Cost model](#9-cost-model)

---

## 1. Architecture Overview

```
  Client (HTTP / Streamlit UI)
          │
          ▼
  ┌───────────────┐
  │  FastAPI v2   │  api.py   :8001
  └──────┬────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────┐
  │                    IMS Pipeline (ims/)                   │
  │                                                          │
  │  QueryInterface  ──►  TaskAnalyzer                       │
  │       │                    │                             │
  │       │            degrees → indices                     │
  │       │                    │                             │
  │       ▼                    ▼                             │
  │  PlanOptimizer  ◄──  MetadataManager  ─────────────────┐ │
  │       │               (psycopg2 pool)                  │ │
  │       │  sequential / parallel plan                    │ │
  │       ▼                                                │ │
  │  SubqueryDistributor  ── TileDB slices ──►  TileDB     │ │
  │       │                                                │ │
  │       ▼                                                │ │
  │  Accumulator  ──►  result + stats                      │ │
  │                                                        │ │
  └────────────────────────────────────────────────────────┼─┘
                                                           │
                         ┌─────────────────────────────────┘
                         │  catalogue lookups + query_log writes
                         ▼
            ┌─────────────────────┐       ┌─────────────────────┐
            │   PostgreSQL 16     │       │  TileDB dense array  │
            │   db: pam           │       │  tiledb_store/pam_co │
            │                     │       │                      │
            │  • metadata         │       │  dims: time×lat×lon  │
            │  • coord_axis       │       │  attr: co (float32)  │
            │  • query_log        │       │  tile: 4×90×144      │
            │                     │       │  compression: Zstd-5 │
            └─────────────────────┘       └─────────────────────┘


  ─ ─ ─ ─ ─ ─ ─ ─ ─  benchmark only (no IMS involvement)  ─ ─ ─ ─ ─ ─ ─ ─ ─

  bench/run_benchmark.py
       │
       ├──► psycopg2 ──► grid_flat (314 MB unlogged table, pure-PG contestant)
       │                  SELECT AVG(value) FROM grid_flat WHERE ...
       │
       └──► QueryInterface.execute()  (v2 path, same IMS pipeline as above)
```

---

## 2. Prerequisites

### 2.1 Operating system

Ubuntu 22.04 LTS (tested). Should work on any Debian-based Linux.

### 2.2 System packages

```bash
sudo apt-get update
sudo apt-get install -y \
    python3.10 python3.10-venv python3-pip \
    postgresql-16 postgresql-client-16 \
    libpq-dev \
    libproj-dev proj-data proj-bin \
    libgeos-dev libgeos++-dev \
    build-essential git curl
```

> **Why libproj / libgeos?** The Streamlit UI uses Cartopy for map rendering.
> Cartopy's C extensions link against PROJ and GEOS at install time.
> Without them, `pip install cartopy` will fail.

### 2.3 PostgreSQL 16 — install on Ubuntu 22.04

If `postgresql-16` is not available in the default repos:

```bash
# Add the official PostgreSQL APT repository
sudo apt-get install -y ca-certificates gnupg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/postgresql.gpg
echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] \
  https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt-get update
sudo apt-get install -y postgresql-16
sudo systemctl enable --now postgresql
```

### 2.4 Python version

Python **3.10** or later. Check with `python3 --version`.

---

## 3. Setup

### 3.1 Clone the repository

```bash
git clone https://github.com/varunjha089/pam-polystore.git
cd pam-polystore
```

### 3.2 Create and activate the virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3.3 Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Then install Streamlit separately (avoids pydantic v1/v2 conflicts):

```bash
pip install streamlit==1.56.0
```

### 3.4 Create the PostgreSQL database and schema

```bash
# Create the database and user
sudo -u postgres psql -c "CREATE DATABASE pam;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"

# Apply schema: metadata, coord_axis, query_log tables
sudo -u postgres psql -d pam -f 01_schema_v2.sql

# Apply schema: grid_flat table (pure-PG benchmark contestant)
sudo -u postgres psql -d pam -f sql/02_schema_grid_flat.sql
```

---

## 4. Load Data

The raw NetCDF4 files and TileDB binary array are not stored in this repo
(too large). You need the 16-month MERRA-2 dataset to re-generate them.

### 4.1 Obtain the MERRA-2 data

Download 16 months of `tavgM_2d_chm_Nx` files (Jan 2019 – Apr 2020) from
NASA Earthdata: https://disc.gsfc.nasa.gov/

Expected filenames:
```
MERRA2_400.tavgM_2d_chm_Nx.YYYYMM.nc4   (16 files, ~18 MB each)
```

Place them in `dataset/` (or symlink: `ln -s /path/to/your/data dataset`).

### 4.2 Build the TileDB array

```bash
source venv/bin/activate
python3 build_tiledb.py
# Creates: tiledb_store/pam_co   (~11 MB, Zstd-5 compressed)
```

### 4.3 Populate PostgreSQL metadata and coordinate axis

The metadata rows and `coord_axis` entries are inserted automatically by
`build_tiledb.py` during the TileDB build step.

Verify:
```bash
sudo -u postgres psql -d pam -c "SELECT COUNT(*) FROM metadata;"
# Should return 16

sudo -u postgres psql -d pam -c "SELECT COUNT(*) FROM coord_axis;"
# Should return 937  (361 lat + 576 lon)
```

### 4.4 Load grid_flat (benchmark only)

This step loads 3.3 M rows into the flat relational table for benchmarking.
It takes ~2 minutes and produces a 314 MB table.

```bash
source venv/bin/activate
python3 scripts/load_grid_flat.py
```

### 4.5 Calibrate the cost model (optional — results already on disk)

```bash
source venv/bin/activate
python3 calibrate_cost_model.py
# Writes: calibration_results.json  (α, β, R²)
```

---

## 5. Run the Services

### 5.1 Start both services with one script

```bash
chmod +x run_v2.sh
./run_v2.sh start
```

This starts:
- **FastAPI v2** on port `8001` → `logs/api.log`
- **Streamlit v2** on port `8502` → `logs/ui.log`

Check status:
```bash
./run_v2.sh status
```

Stop:
```bash
./run_v2.sh stop
```

### 5.2 Start services manually (alternative)

```bash
source venv/bin/activate

# Terminal 1 — FastAPI
uvicorn api:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 — Streamlit UI
streamlit run app_v2.py --server.port 8502 --server.address 0.0.0.0
```

### 5.3 Access the UI

| Surface | URL |
|---|---|
| Streamlit v2 UI | http://localhost:8502 |
| FastAPI interactive docs | http://localhost:8001/docs |

If running on a remote server, SSH-tunnel port 8502 to your local machine:
```bash
ssh -L 8502:localhost:8502 user@your-server
```
Then open http://localhost:8502 in your browser.

---

## 6. API Reference

### POST `/ims/query` — execute a query

```bash
curl -s -X POST http://localhost:8001/ims/query \
  -H "Content-Type: application/json" \
  -d '{
    "parameter": "COCL",
    "time": "201901",
    "region": {"lat": [8, 35], "lon": [68, 97]}
  }' | python3 -m json.tool
```

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `shape` | `[int, int]` | Result array dimensions `[n_lat, n_lon]` |
| `data` | `[[float]]` | 2-D grid of CO values (kg/kg) |
| `stats.mean` | float | Mean over valid cells |
| `stats.max` | float | Maximum value |
| `stats.min` | float | Minimum value |
| `stats.count` | int | Number of valid (non-fill) cells |
| `time_steps` | `[str]` | Time step(s) returned |

**Time range query (multi-month):**

```bash
curl -s -X POST http://localhost:8001/ims/query \
  -H "Content-Type: application/json" \
  -d '{
    "parameter": "COCL",
    "time": {"from": "201901", "to": "201906"},
    "region": {"lat": [8, 35], "lon": [68, 97]}
  }'
```

### POST `/ims/explain` — inspect the query plan (no execution)

```bash
curl -s -X POST http://localhost:8001/ims/explain \
  -H "Content-Type: application/json" \
  -d '{
    "parameter": "COCL",
    "time": "201901",
    "region": {"lat": [8, 35], "lon": [68, 97]}
  }' | python3 -m json.tool
```

Returns the IMS plan: strategy (`sequential` / `parallel`), cost estimate,
subquery list, and cost model parameters (α, β, R²).

---

## 7. Run the Benchmark

The Day 4 fair head-to-head benchmark compares **pure-PG** (grid_flat) vs **v2**
(TileDB + IMS) across 6 query classes, 10 warm runs each, measured in-process
(no HTTP overhead).

```bash
source venv/bin/activate
python3 bench/run_benchmark.py
```

Expected output (approximate — actual numbers vary by hardware):

| Query | pure_pg (ms) | v2 (ms) | Winner |
|---|---|---|---|
| Q1 — single cell | ~17 | ~25 | pure_pg |
| Q2 — India, 1 month | ~24 | ~24 | tie |
| Q3 — Asia, 1 month | ~35 | ~24 | **v2 1.5×** |
| Q4 — India, 6 months | ~60 | ~50 | **v2 1.2×** |
| Q5 — global, 1 month | ~73 | ~32 | **v2 2.3×** |
| Q6 — point, 16 months | ~17 | ~86 | pure_pg |

Results are written to `bench/results_fair.csv`.

Regenerate plots:
```bash
python3 bench/make_plots.py
# Writes: bench/latency_chart.png, bench/storage_chart.png
```

---

## 8. Project Layout

```
pam-polystore/
│
├── api.py                      FastAPI app — /ims/query, /ims/explain, /query
├── app_v2.py                   Streamlit v2 UI (map + IMS trace panel)
├── run_v2.sh                   Start/stop/status script for both services
│
├── ims/                        Six-module IMS
│   ├── __init__.py
│   ├── query_interface.py      Entry point — orchestrates the pipeline
│   ├── metadata_manager.py     PostgreSQL access (connection pool)
│   ├── task_analyzer.py        Classifies query; resolves degrees → indices
│   ├── plan_optimizer.py       Cost model; sequential vs parallel decision
│   ├── subquery_distributor.py Executes TileDB slices (sequential / parallel)
│   └── accumulator.py          Merges slices; computes stats; masks fill values
│
├── sql/
│   └── 02_schema_grid_flat.sql grid_flat table + indexes (benchmark only)
├── 01_schema_v2.sql            metadata, coord_axis, query_log tables
├── day1_schema_snapshot.sql    Day 1 schema reference snapshot
│
├── scripts/
│   └── load_grid_flat.py       Bulk-loads grid_flat from TileDB (~2 min)
├── build_tiledb.py             Ingests NetCDF4 → TileDB array + metadata rows
├── calibrate_cost_model.py     Fits α, β, R² from TileDB timing samples
│
├── bench/
│   ├── run_benchmark.py        6-query × 10-run fair benchmark harness
│   ├── make_plots.py           Generates latency + storage PNG charts
│   ├── results_fair.csv        Latest benchmark results
│   ├── results_v1_included.csv Results including v1 (.npy) for reference
│   ├── latency_chart.png       Latency bar chart
│   └── storage_chart.png       Storage comparison chart
│
├── calibration_results.json    α=6.792e-05, β=3.2323, R²=0.6092
├── calibration_results.txt     Human-readable calibration summary
├── calibration_plot.png        Calibration scatter + fit plot
├── report.md                   Full project report (6479 words)
├── docs/
│   └── query_dsl.md            IMS query DSL specification
│
├── requirements.txt            Python dependencies (this file)
└── .gitignore
```

**Not tracked in git (too large or regeneratable):**

| Path | Size | How to recreate |
|---|---|---|
| `venv/` | ~456 MB | `python3 -m venv venv && pip install -r requirements.txt` |
| `dataset/` | ~298 MB | Download from NASA Earthdata (see §4.1) |
| `tiledb_store/` | ~11 MB | `python3 build_tiledb.py` |
| `grids/` | ~13 MB | v1 legacy; not needed for v2 |

---

## 9. Cost Model

The IMS `PlanOptimizer` uses a linear model calibrated on 55 TileDB slice
measurements to decide whether to run subqueries sequentially or in parallel:

```
cost_ms = α × area_cells + β
```

| Parameter | Value | Meaning |
|---|---|---|
| α (alpha) | 6.792 × 10⁻⁵ ms/cell | Marginal cost per additional grid cell |
| β (beta) | 3.2323 ms | Fixed cost: file open + tile decompress |
| R² | 0.6092 | Explained variance (see report.md §6.3 for discussion) |

The optimizer chooses **parallel** execution when
`N × cost_per_subquery > cost_per_subquery + 5 ms thread_overhead`
(i.e., N ≥ 2 and the region is large enough), otherwise **sequential**.

---

## License

Academic project — M.Tech Advanced Databases, 2026.
MERRA-2 data courtesy of NASA Global Modeling and Assimilation Office.
