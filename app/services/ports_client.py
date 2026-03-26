"""
SQL Server client for fetching port data from EDNaviGas.dbo.SeaPorts.

Production notes:
- pymssql is synchronous; all DB calls run in a thread-pool executor so the
  async event loop is never blocked.
- A simple connection pool is maintained via a threading.Lock-guarded list.
  pymssql has no built-in async pool, so we manage a fixed-size pool manually.
- Transient errors (deadlock, connection reset) are retried with exponential
  back-off up to MAX_RETRIES times.
- All queries use parameterised %s placeholders — no string interpolation of
  user-supplied values.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

import pymssql

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry config
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.2  # seconds; doubles each attempt

# Transient pymssql error numbers worth retrying
_TRANSIENT_ERRORS = {
    1205,   # deadlock victim
    -2,     # timeout
    10054,  # connection reset by peer
    10060,  # connection timed out
}

_SELECT_COLUMNS = """
    PortCodeID    AS port_id,
    PortCode      AS port_code,
    PortName      AS port_name,
    type          AS port_type,
    geometry_type AS geometry_type,
    Portterminal  AS port_terminal,
    Latitude      AS latitude,
    Longitude     AS longitude
"""

_TABLE = "[EDNaviGas].[dbo].[SeaPorts]"


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, pymssql.OperationalError):
        return True
    if isinstance(exc, pymssql.DatabaseError):
        args = exc.args
        if args and isinstance(args[0], int) and args[0] in _TRANSIENT_ERRORS:
            return True
    return False


class PortsClient:
    """Thread-safe, async-friendly SQL Server client with connection pooling."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        database: str,
        port: int = 1433,
        pool_size: int = 5,
        connect_timeout: int = 10,
        login_timeout: int = 10,
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._database = database
        self._port = port
        self._pool_size = pool_size
        self._connect_timeout = connect_timeout
        self._login_timeout = login_timeout

        self._pool: list[pymssql.Connection] = []
        self._lock = threading.Lock()


    def _new_connection(self) -> pymssql.Connection:
        return pymssql.connect(
            server=self._host,
            user=self._user,
            password=self._password,
            database=self._database,
            port=str(self._port),
            timeout=self._connect_timeout,
            login_timeout=self._login_timeout,
        )

    @contextmanager
    def _get_conn(self):
        """Borrow a connection from the pool; return it when done."""
        conn = None
        with self._lock:
            if self._pool:
                conn = self._pool.pop()

        if conn is None:
            conn = self._new_connection()

        try:
            yield conn
            # Return healthy connection to pool
            with self._lock:
                if len(self._pool) < self._pool_size:
                    self._pool.append(conn)
                    conn = None  # don't close it
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _run_with_retry(self, fn, *args, **kwargs):
        """Run a synchronous callable, retrying on transient DB errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not _is_transient(exc) or attempt == _MAX_RETRIES - 1:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Transient DB error (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1, _MAX_RETRIES, delay, exc,
                )
                time.sleep(delay)
                # Discard potentially broken connection from pool
                with self._lock:
                    self._pool.clear()
        raise last_exc  # unreachable but satisfies type checkers

    def _fetch_ports_sync(self, page: int, page_size: int) -> dict[str, Any]:
        offset = (page - 1) * page_size

        def _execute():
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {_TABLE}")
                    total: int = cur.fetchone()[0]

                with conn.cursor(as_dict=True) as cur:
                    cur.execute(
                        f"""
                        SELECT {_SELECT_COLUMNS}
                        FROM   {_TABLE}
                        ORDER  BY PortCodeID
                        OFFSET %d ROWS FETCH NEXT %d ROWS ONLY
                        """ % (offset, page_size)
                    )
                    items: list[dict] = cur.fetchall()

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": max(1, (total + page_size - 1) // page_size),
            }

        return self._run_with_retry(_execute)

    def _search_ports_sync(self, q: str, limit: int) -> list[dict[str, Any]]:
        like_param = f"%{q}%"
        # Build TOP clause via f-string (limit is a validated int, not user input).
        # Keep %s placeholders for pymssql parameterisation of the LIKE values.
        sql = f"""
            SELECT TOP {limit}
                {_SELECT_COLUMNS}
            FROM   {_TABLE}
            WHERE  PortName LIKE %s
               OR  PortCode LIKE %s
            ORDER  BY PortName
        """

        def _execute():
            with self._get_conn() as conn:
                with conn.cursor(as_dict=True) as cur:
                    cur.execute(sql, (like_param, like_param))
                    return cur.fetchall()

        return self._run_with_retry(_execute)

    async def get_ports(self, page: int, page_size: int) -> dict[str, Any]:
        """Fetch a paginated page of ports. Non-blocking — runs in thread pool."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, self._fetch_ports_sync, page, page_size
            )
        except Exception as exc:
            logger.error("get_ports failed (page=%d, page_size=%d): %s", page, page_size, exc)
            raise

    async def search_ports(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search ports by name or code. Non-blocking — runs in thread pool."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, self._search_ports_sync, q, limit
            )
        except Exception as exc:
            logger.error("search_ports failed (q=%r, limit=%d): %s", q, limit, exc)
            raise

    def close(self) -> None:
        """Close all pooled connections. Call on app shutdown."""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()
