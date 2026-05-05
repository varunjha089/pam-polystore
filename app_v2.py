"""
PAM v2 — Streamlit UI

Talks to the v2 FastAPI service on port 8001 via /ims/query.
Differences from v1:
  - Sliders use REAL DEGREES (lat -90..90, lon -180..180), not array indices.
  - Time control supports BOTH single date AND date range.
  - New "Query Plan" tab visualizes the IMS pipeline trace.
  - Range queries get an extra time-series chart.

Run with:
    cd ~/claude_db_project
    source venv/bin/activate
    streamlit run app_v2.py --server.port 8502 --server.address 0.0.0.0
"""
import os
import json
import requests
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
API_BASE = os.environ.get("PAM_API_BASE", "http://localhost:8001")
IMS_QUERY_URL    = f"{API_BASE}/ims/query"
IMS_HEALTH_URL   = f"{API_BASE}/ims/health"
IMS_TIMESTEPS    = f"{API_BASE}/ims/time_steps"

st.set_page_config(page_title="PAM v2 — Polystore Climate Data", layout="wide")

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("🌍 PAM v2 — Polystore Climate Data Query System")
st.caption("PostgreSQL (metadata + coords) ⟷ TileDB (array store), with a 6-module IMS in front.")

# Health check (small, top-right)
try:
    h = requests.get(IMS_HEALTH_URL, timeout=2).json()
    st.success(f"v2 backend OK · {h['time_steps_loaded']} time steps loaded · version {h['version']}", icon="✅")
except Exception as e:
    st.error(f"v2 backend unreachable at {API_BASE} — is the FastAPI service running on port 8001? ({e})")
    st.stop()

# --------------------------------------------------------------------------
# Sidebar — query controls
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Query Controls")

    # Get available time steps from the backend (so the UI is always in sync with the DB)
    try:
        ts_list = requests.get(IMS_TIMESTEPS, timeout=2).json()["time_steps"]
    except Exception:
        ts_list = ["201901"]   # safety default

    parameter = st.selectbox("Parameter", ["COCL"], index=0,
                             help="Carbon monoxide column burden. Day 4 will add COSC, COEM, TO3.")

    mode = st.radio("Time mode", ["Single", "Range"], horizontal=True)
    if mode == "Single":
        time_value = st.selectbox("Time step (YYYYMM)", ts_list, index=0)
        time_payload = time_value
    else:
        c1, c2 = st.columns(2)
        with c1:
            ts_from = st.selectbox("From", ts_list, index=0)
        with c2:
            ts_to = st.selectbox("To", ts_list, index=min(5, len(ts_list)-1))
        time_payload = {"from": ts_from, "to": ts_to}

    st.markdown("---")
    st.subheader("Region (degrees)")
    use_region = st.checkbox("Restrict to region", value=True)

    if use_region:
        # Defaults centered on India so first screenshots are interesting, not all blue ocean
        lat_lo, lat_hi = st.slider("Latitude (°)",   -90.0,  90.0, ( 8.0,  35.0), step=0.5)
        lon_lo, lon_hi = st.slider("Longitude (°)", -180.0, 180.0, (68.0,  97.0), step=0.5)
        region = {"lat": [lat_lo, lat_hi], "lon": [lon_lo, lon_hi]}
    else:
        region = None

    st.markdown("---")
    run = st.button("🚀 Run Query", type="primary", use_container_width=True)


# --------------------------------------------------------------------------
# Build payload
# --------------------------------------------------------------------------
payload = {
    "parameter": parameter,
    "time": time_payload,
    "region": region,
}

with st.expander("🔧 Query payload (DSL)", expanded=False):
    st.code(json.dumps(payload, indent=2), language="json")


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
tab_map, tab_heat, tab_plan, tab_series = st.tabs([
    "🌍 Geographic CO Map",
    "🔥 Heatmap (Indices)",
    "🧭 Query Plan (IMS trace)",
    "📈 Time Series",
])


def _post_query(body):
    """Run the query against /ims/query. Surface backend errors cleanly."""
    r = requests.post(IMS_QUERY_URL, json=body, timeout=30)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
if run:
    try:
        with st.spinner("Asking the IMS…"):
            result = _post_query(payload)
    except Exception as e:
        st.error(f"Query failed: {e}")
        st.stop()

    # ---------- Top-level statistics ----------
    stats = result["stats"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean",  f"{stats['mean']:.6f}" if stats['mean'] is not None else "—")
    c2.metric("Max",   f"{stats['max']:.6f}"  if stats['max']  is not None else "—")
    c3.metric("Min",   f"{stats['min']:.6f}"  if stats['min']  is not None else "—")
    c4.metric("Cells", f"{stats['count']:,}")

    # ---------- Pull the raw data (a list, possibly nested) ----------
    arr = np.asarray(result["data"], dtype=np.float32)
    is_range = arr.ndim == 3                 # (T, lat, lon) for range, (lat, lon) for single
    time_steps = result["time_steps"]

    # Mask MERRA-2 fill values for plotting
    arr_masked = np.where(np.isfinite(arr) & (arr < 1e10), arr, np.nan)

    # Reconstruct lat/lon arrays for the chosen region (so cartopy gets real coords)
    if region is not None:
        # We can compute these by linspacing inside the requested box -- the array
        # backend already cropped to those indices. Use the global grid resolution.
        n_lat_total, n_lon_total = 361, 576
        lat_full = np.linspace(-90, 90, n_lat_total)
        lon_full = np.linspace(-180, 180-(360.0/n_lon_total), n_lon_total)
        lat_mask = (lat_full >= region["lat"][0]) & (lat_full <= region["lat"][1])
        lon_mask = (lon_full >= region["lon"][0]) & (lon_full <= region["lon"][1])
        lats = lat_full[lat_mask]
        lons = lon_full[lon_mask]
    else:
        lats = np.linspace(-90, 90, arr.shape[-2])
        lons = np.linspace(-180, 180-(360.0/arr.shape[-1]), arr.shape[-1])

    # ---------- Pick which slice to show on the map/heatmap tabs ----------
    if is_range:
        st.info(f"Range query: {len(time_steps)} time steps. Showing first slice ({time_steps[0]}). "
                "See the Time Series tab for the full series.")
        slice_2d = arr_masked[0]
        title_suffix = f"{time_steps[0]} (first of {len(time_steps)})"
    else:
        slice_2d = arr_masked
        title_suffix = time_steps[0]

    # ============= Tab 1: real-coordinate map =============
    with tab_map:
        st.subheader("🌍 Geographic CO Map")
        fig = plt.figure(figsize=(9, 4.5))
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.coastlines(linewidth=0.6)
        ax.add_feature(cfeature.BORDERS, linewidth=0.4, edgecolor="gray")

        mesh = ax.pcolormesh(lons, lats, slice_2d,
                             cmap="hot", shading="auto",
                             transform=ccrs.PlateCarree())
        plt.colorbar(mesh, ax=ax, orientation="vertical", label="CO concentration (kg m⁻²)")
        ax.set_title(f"Global CO Map · {title_suffix}")
        st.pyplot(fig)

    # ============= Tab 2: index-space heatmap =============
    with tab_heat:
        st.subheader("🔥 Index-based Heatmap")
        fig2, ax2 = plt.subplots(figsize=(7, 4))
        im = ax2.imshow(slice_2d, origin="lower", aspect="auto", cmap="viridis")
        plt.colorbar(im, ax=ax2)
        ax2.set_title(f"Heatmap (array indices) · {title_suffix}")
        ax2.set_xlabel("Longitude index")
        ax2.set_ylabel("Latitude index")
        st.pyplot(fig2)

    # ============= Tab 3: IMS trace =============
    with tab_plan:
        st.subheader("🧭 IMS Query Plan")
        trace = result.get("_trace", {})
        total_ms = trace.get("total_ms", 0.0)

        # Hero metric: end-to-end latency
        st.metric("Total time (end-to-end)", f"{total_ms:.2f} ms")

        # Stage-by-stage breakdown, in execution order
        stages = trace.get("stages", [])
        st.markdown("#### Pipeline stages")
        stage_rows = []
        for s in stages:
            row = {"stage": s["stage"]}
            for k, v in s.items():
                if k == "stage": continue
                row[k] = v if not isinstance(v, list) else json.dumps(v)
            stage_rows.append(row)
        st.dataframe(stage_rows, use_container_width=True, hide_index=True)

        # Drill-down: per-subquery TileDB timings, if present
        for s in stages:
            if s["stage"] == "distribute" and "timings_ms" in s:
                st.markdown("#### Per-subquery TileDB timings")
                st.dataframe(s["timings_ms"], use_container_width=True, hide_index=True)
                # Quick visual
                if len(s["timings_ms"]) > 1:
                    figp, axp = plt.subplots(figsize=(7, 2.6))
                    xs = [t["time_step"] for t in s["timings_ms"]]
                    ys = [t["ms"]        for t in s["timings_ms"]]
                    axp.bar(xs, ys, color="#1f4e79")
                    axp.set_ylabel("ms")
                    axp.set_title("TileDB read time per sub-query")
                    plt.xticks(rotation=45, ha="right")
                    st.pyplot(figp)

        # Show the full plan + result shape so reviewers can sanity-check
        with st.expander("Raw trace JSON"):
            st.code(json.dumps(trace, indent=2), language="json")
        st.caption(f"Result shape: {result['shape']} · Units: {result.get('units','')}")

    # ============= Tab 4: time series (only meaningful for range queries) =============
    with tab_series:
        st.subheader("📈 Regional mean over time")
        if not is_range:
            st.info("Switch to **Range** time mode in the sidebar to see a multi-month time series.")
        else:
            # Compute per-month spatial mean (masking fill values)
            monthly_mean = np.nanmean(arr_masked.reshape(arr_masked.shape[0], -1), axis=1)
            monthly_max  = np.nanmax (arr_masked.reshape(arr_masked.shape[0], -1), axis=1)

            figs, axs = plt.subplots(figsize=(9, 3.8))
            axs.plot(time_steps, monthly_mean, marker="o", label="regional mean")
            axs.plot(time_steps, monthly_max,  marker="s", label="regional max", alpha=0.6)
            axs.set_ylabel("CO (kg m⁻²)")
            axs.set_xlabel("Time step")
            axs.set_title(f"Regional CO over time · {len(time_steps)} months")
            axs.legend()
            plt.xticks(rotation=45, ha="right")
            st.pyplot(figs)

            # Tabular view too
            st.dataframe(
                [{"time_step": t, "mean": float(m), "max": float(x)}
                 for t, m, x in zip(time_steps, monthly_mean, monthly_max)],
                use_container_width=True, hide_index=True,
            )

else:
    st.info("Set your query parameters in the sidebar and press **Run Query**.")
