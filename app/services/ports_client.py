"""
SQL Server client for fetching port data from EDNaviGas.dbo.Ports.
Uses pymssql — no system ODBC driver required.
"""
import logging
from typing import Any

import pymssql

logger = logging.getLogger(__name__)


class PortsClient:
    def __init__(self, host: str, user: str, password: str, database: str, port: int = 1433) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._database = database
        self._port = port

    def _connect(self):
        return pymssql.connect(
            server=self._host,
            user=self._user,
            password=self._password,
            database=self._database,
            port=str(self._port),
        )

    async def get_ports(self, page: int, page_size: int) -> dict[str, Any]:
        """Fetch paginated active ports with lat/lon from the database."""
        offset = (page - 1) * page_size
        query = """
            SELECT
                int_PortID   AS port_id,
                PortCode     AS port_code,
                Port         AS port_name,
                CountryCode  AS country_code,
                ZoneCode     AS zone_code,
                IsEUPort     AS is_eu_port,
                Latitude     AS latitude,
                Longitude    AS longitude,
                IsActive     AS is_active
            FROM [EDNaviGas].[dbo].[Ports]
            WHERE IsActive = 1
            ORDER BY Port
            OFFSET %d ROWS FETCH NEXT %d ROWS ONLY
        """ % (offset, page_size)

        count_query = "SELECT COUNT(*) FROM [EDNaviGas].[dbo].[Ports] WHERE IsActive = 1"

        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(count_query)
                    total = cur.fetchone()[0]

                with conn.cursor(as_dict=True) as cur:
                    cur.execute(query)
                    items = cur.fetchall()
            finally:
                conn.close()

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            }
        except Exception as exc:
            logger.error("Failed to fetch ports from database: %s", exc)
            raise

    async def search_ports(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search active ports by port name, port code, or country code (case-insensitive)."""
        like_param = f"%{q}%"
        query = f"""
            SELECT TOP {limit}
                int_PortID   AS port_id,
                PortCode     AS port_code,
                Port         AS port_name,
                CountryCode  AS country_code,
                ZoneCode     AS zone_code,
                IsEUPort     AS is_eu_port,
                Latitude     AS latitude,
                Longitude    AS longitude,
                IsActive     AS is_active
            FROM [EDNaviGas].[dbo].[Ports]
            WHERE IsActive = 1
              AND (
                    Port        LIKE %s
                 OR PortCode    LIKE %s
                 OR CountryCode LIKE %s
              )
            ORDER BY Port
        """

        try:
            conn = self._connect()
            try:
                with conn.cursor(as_dict=True) as cur:
                    cur.execute(query, (like_param, like_param, like_param))
                    items = cur.fetchall()
            finally:
                conn.close()
            return items
        except Exception as exc:
            logger.error("Failed to search ports: %s", exc)
            raise
