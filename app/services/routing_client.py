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

    async def compute_route(self, payload: dict) -> dict:
        """
        Obtain a token, open the WebSocket, send the payload, collect all
        messages until the server closes the connection, and return them.

        Automatically retries once with a fresh token on a 401/403 close code.
        Retries up to 2 times on a 410 session-unavailable response.
        """
        token = await self._auth_client.get_token()
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                return await self._connect_and_collect(token, payload)
            except websockets.exceptions.InvalidStatus as exc:
                if exc.response.status_code in (401, 403):
                    logger.warning("WebSocket auth rejected (%s), refreshing token and retrying",
                                   exc.response.status_code)
                    self._auth_client.invalidate()
                    token = await self._auth_client.get_token()
                    last_exc = exc
                    continue
                raise RoutingConnectionError(str(exc)) from exc
            except RoutingError as exc:
                # Retry on 410 session-unavailable (transient ABB-side issue)
                if "410" in str(exc) and attempt < 2:
                    logger.warning("ABB 410 session error (attempt %d/3), retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    last_exc = exc
                    continue
                raise

        raise last_exc

    async def _connect_and_collect(self, token: str, payload: dict) -> dict:
        try:
            # websockets v12 legacy client uses extra_headers (not additional_headers)
            async with websockets.connect(
                self._settings.routing_ws_url,
                extra_headers={"Authorization": f"Bearer {token}"},
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

    async def _collect(self, ws) -> dict:
        """Receive the first message from the server and return it immediately."""
        try:
            raw = await asyncio.wait_for(
                ws.recv(),
                timeout=self._settings.ws_recv_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise RoutingConnectionError(
                f"No response received within {self._settings.ws_recv_timeout}s"
            ) from exc
        except websockets.exceptions.ConnectionClosed as exc:
            raise RoutingConnectionError(f"Connection closed before response: {exc}") from exc

        msg = json.loads(raw)
        logger.info("Received response from routing API")

        # ABB returns typed error envelopes — surface them as RoutingError
        if isinstance(msg, dict):
            # { "type": "error", "message": "..." }
            if msg.get("type") == "error":
                raise RoutingError(msg.get("message", str(msg)))

            # { "errors": [{"status": 410, "title": "Connection", ...}], ... }
            errors = msg.get("errors")
            if errors and isinstance(errors, list):
                first = errors[0]
                status = first.get("status")
                title = first.get("title", "")
                detail = first.get("detail", str(first))
                if status == 410:
                    # Session expired / no valid connection on ABB side — caller should retry
                    raise RoutingError(f"ABB routing session unavailable ({status} {title}): {detail}")
                raise RoutingError(f"ABB routing error ({status} {title}): {detail}")

        return msg
