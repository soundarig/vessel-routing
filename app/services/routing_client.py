import asyncio
import json
import logging

import websockets
import websockets.exceptions

from app.config import Settings
from app.services.auth_client import AuthClient, AuthError

logger = logging.getLogger(__name__)


class RoutingConnectionError(Exception):
    def __init__(self, reason: str):
        super().__init__(f"WebSocket connection failed: {reason}")


class RoutingError(Exception):
    def __init__(self, detail: str):
        super().__init__(f"Routing API error: {detail}")


class RoutingClient:
    """Connects to the vessel routing WebSocket API and collects route results."""

    def __init__(self, auth_client: AuthClient, settings: Settings) -> None:
        self._auth_client = auth_client
        self._settings = settings

    async def compute_route(self, payload: dict) -> list[dict]:
        """
        Obtain a token, open the WebSocket, send the payload, collect all
        messages until the server closes the connection, and return them.

        Automatically retries once with a fresh token on a 401/403 close code.
        """
        token = await self._auth_client.get_token()
        try:
            return await self._connect_and_collect(token, payload)
        except websockets.exceptions.InvalidStatus as exc:
            # 401 / 403 → invalidate cached token and retry once
            if exc.response.status_code in (401, 403):
                logger.warning("WebSocket auth rejected (%s), refreshing token and retrying",
                               exc.response.status_code)
                self._auth_client.invalidate()
                token = await self._auth_client.get_token()
                return await self._connect_and_collect(token, payload)
            raise RoutingConnectionError(str(exc)) from exc

    async def _connect_and_collect(self, token: str, payload: dict) -> list[dict]:
        try:
            async with websockets.connect(
                self._settings.routing_ws_url,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=self._settings.ws_connect_timeout,
            ) as ws:
                await ws.send(json.dumps(payload))
                logger.debug("Routing request sent, collecting messages")
                return await self._collect(ws)

        except (RoutingError, RoutingConnectionError):
            raise
        except websockets.exceptions.WebSocketException as exc:
            raise RoutingConnectionError(str(exc)) from exc
        except OSError as exc:
            raise RoutingConnectionError(str(exc)) from exc

    async def _collect(self, ws) -> list[dict]:
        messages: list[dict] = []
        try:
            while True:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=self._settings.ws_recv_timeout,
                )
                msg = json.loads(raw)
                messages.append(msg)
                if isinstance(msg, dict) and msg.get("type") == "error":
                    raise RoutingError(msg.get("message", str(msg)))
        except asyncio.TimeoutError as exc:
            raise RoutingConnectionError(
                f"No message received within {self._settings.ws_recv_timeout}s"
            ) from exc
        except websockets.exceptions.ConnectionClosed:
            pass  # normal — server closed after sending all data

        logger.info("Collected %d messages from routing API", len(messages))
        return messages
