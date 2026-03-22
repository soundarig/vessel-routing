"""
SQL Server client for fetching port data from EDNaviGas.dbo.Ports.
"""
import logging
from typing import Any

import aioodbc

logger = logging.getLogger(__name__)


class PortsClient:
    def __init__(self, connection_string: str) -> None:
        self._conn_str = connection_string

    async def get_all_ports(self) -> list[dict[str, Any]]:
        """Fetch all active ports with lat/lon from the database."""
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
        """
        try:
            async with await aioodbc.connect(dsn=self._conn_str) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query)
                    columns = [col[0] for col in cur.description]
                    rows = await cur.fetchall()
                    return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            logger.error("Failed to fetch ports from database: %s", exc)
            raise
