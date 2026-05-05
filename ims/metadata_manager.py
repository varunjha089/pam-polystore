"""
MetadataManager — wraps PostgreSQL access for the IMS.

Owns the connection pool, exposes high-level methods that other IMS modules
need: lookup files for a time range, resolve degrees to indices via coord_axis,
log query traces.

This is intentionally the only module in the IMS that touches psycopg2 directly.
"""
import psycopg2
from psycopg2 import pool
from typing import List, Optional, Tuple, Dict, Any

PG = dict(dbname="pam", user="postgres", password="postgres", host="localhost")


class MetadataManager:
    _pool: Optional[pool.SimpleConnectionPool] = None

    def __init__(self):
        if MetadataManager._pool is None:
            MetadataManager._pool = pool.SimpleConnectionPool(1, 8, **PG)

    # ---- helpers ----
    def _conn(self):
        return MetadataManager._pool.getconn()

    def _put(self, c):
        MetadataManager._pool.putconn(c)

    # ---- queries ----
    def lookup_time_step(self, parameter: str, time_step: str) -> Optional[Dict[str, Any]]:
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("""SELECT id, time_step, year, month, parameter, units,
                                  lat_min, lat_max, lon_min, lon_max,
                                  n_lat, n_lon, tiledb_uri,
                                  data_min, data_max, data_mean
                           FROM metadata
                           WHERE parameter=%s AND time_step=%s;""",
                        (parameter, time_step))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            cur.close()
            return dict(zip(cols, row)) if row else None
        finally:
            self._put(c)

    def lookup_time_range(self, parameter: str, ts_from: str, ts_to: str) -> List[Dict]:
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("""SELECT id, time_step, year, month, parameter, units,
                                  lat_min, lat_max, lon_min, lon_max,
                                  n_lat, n_lon, tiledb_uri,
                                  data_min, data_max, data_mean
                           FROM metadata
                           WHERE parameter=%s
                             AND time_step BETWEEN %s AND %s
                           ORDER BY time_step;""",
                        (parameter, ts_from, ts_to))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            cur.close()
            return [dict(zip(cols, r)) for r in rows]
        finally:
            self._put(c)

    def degrees_to_indices(self, parameter: str, axis: str,
                           lo_deg: float, hi_deg: float) -> Tuple[int, int]:
        """Resolve a degree range to inclusive index bounds via coord_axis."""
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("""SELECT MIN(idx), MAX(idx) FROM coord_axis
                           WHERE parameter=%s AND axis=%s
                             AND value BETWEEN %s AND %s;""",
                        (parameter, axis, lo_deg, hi_deg))
            lo, hi = cur.fetchone()
            cur.close()
            if lo is None:
                raise ValueError(f"No {axis} indices in range [{lo_deg}, {hi_deg}]")
            return lo, hi
        finally:
            self._put(c)

    def time_step_to_index(self, parameter: str, time_step: str) -> int:
        """Return the 0-based position of `time_step` within all rows for `parameter`."""
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("""SELECT row_number() OVER (ORDER BY time_step) - 1
                           FROM metadata
                           WHERE parameter=%s AND time_step=%s;""",
                        (parameter, time_step))
            row = cur.fetchone()
            cur.close()
            return int(row[0]) if row else -1
        finally:
            self._put(c)

    def all_time_steps(self, parameter: str) -> List[str]:
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT time_step FROM metadata WHERE parameter=%s ORDER BY time_step;",
                        (parameter,))
            out = [r[0] for r in cur.fetchall()]
            cur.close()
            return out
        finally:
            self._put(c)

    def log_query(self, query_json, plan_json, pg_ms, arr_ms, total_ms,
                  result_shape, n_pruned):
        c = self._conn()
        try:
            cur = c.cursor()
            cur.execute("""INSERT INTO query_log
                (query_json, plan_json, pg_time_ms, array_time_ms, total_time_ms,
                 result_shape, n_files_pruned)
                VALUES (%s::jsonb, %s::jsonb, %s, %s, %s, %s, %s);""",
                (query_json, plan_json, pg_ms, arr_ms, total_ms, result_shape, n_pruned))
            c.commit()
            cur.close()
        finally:
            self._put(c)
