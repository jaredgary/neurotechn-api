import os
import logging
from psycopg_pool import ConnectionPool
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_URL = os.getenv("SUPABASE_DB_URL")
if not DB_URL:
    raise ValueError("SUPABASE_DB_URL environment variable is required")

# Pool más conservador para hosting limitado
pool = ConnectionPool(
    conninfo=DB_URL, 
    min_size=2, 
    max_size=8, 
    open=True,
    check=ConnectionPool.check_connection
)

def fetch_df(sql: str, params=None):
    import pandas as pd
    try:
        with pool.connection() as conn:
            return pd.read_sql(sql, conn, params=params)
    except Exception as e:
        logger.error(f"Database query failed: {sql[:100]}... Error: {e}")
        raise HTTPException(503, f"Database error: {str(e)}")

def execute(sql: str, params=None, many: bool = False):
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                if many:
                    cur.executemany(sql, params)
                else:
                    cur.execute(sql, params)
                conn.commit()  # Explicit commit
    except Exception as e:
        logger.error(f"Database execute failed: {sql[:100]}... Error: {e}")
        raise HTTPException(503, f"Database error: {str(e)}")

def fetch_one(sql: str, params=None):
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
    except Exception as e:
        logger.error(f"Database fetch_one failed: {sql[:100]}... Error: {e}")
        return None
