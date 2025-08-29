import os
from typing import Optional
from psycopg_pool import ConnectionPool

DB_URL = os.getenv("SUPABASE_DB_URL")

_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not DB_URL:
            raise RuntimeError("SUPABASE_DB_URL is not set in environment")
        _pool = ConnectionPool(conninfo=DB_URL, min_size=1, max_size=10, open=True)
    return _pool


def fetch_df(sql: str, params=None):
    import pandas as pd

    with _get_pool().connection() as conn:
        return pd.read_sql(sql, conn, params=params)


def execute(sql: str, params=None, many: bool = False):
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            if many:
                cur.executemany(sql, params)
            else:
                cur.execute(sql, params)


def fetch_one(sql: str, params=None):
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

