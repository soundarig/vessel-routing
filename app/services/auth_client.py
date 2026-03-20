import asyncio
import logging
import time

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Authentication failed: {status_code} - {body}")


class AuthClient:
    """Fetches and caches OAuth2 bearer tokens using the client credentials flow."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _is_valid(self) -> bool:
        """Return True if the cached token has more than 30 seconds remaining."""
        return bool(self._token) and time.time() < self._expires_at - 30

    def invalidate(self) -> None:
        """Force the next call to get_token() to fetch a fresh token."""
        self._token = None
        self._expires_at = 0.0

    async def get_token(self) -> str:
        """Return a valid bearer token, fetching a new one when needed."""
        if self._is_valid():
            return self._token  # type: ignore[return-value]
        return await self._fetch_with_retry()

    async def _fetch_with_retry(self) -> str:
        attempts = self._settings.token_retry_attempts
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await self._fetch()
            except AuthError:
                raise  # don't retry on auth errors (bad credentials)
            except Exception as exc:
                last_exc = exc
                if attempt < attempts:
                    wait = self._settings.token_retry_backoff * attempt
                    logger.warning(
                        "Token fetch attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt, attempts, wait, exc,
                    )
                    await asyncio.sleep(wait)

        raise RuntimeError(f"Token fetch failed after {attempts} attempts") from last_exc

    async def _fetch(self) -> str:
        logger.info("Fetching new OAuth2 token")
        async with httpx.AsyncClient(timeout=self._settings.http_timeout) as client:
            response = await client.post(
                self._settings.token_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.oauth_client_id,
                    "client_secret": self._settings.oauth_client_secret,
                    "scope": self._settings.oauth_scope,
                },
            )

        if response.status_code != 200:
            raise AuthError(response.status_code, response.text)

        data = response.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data["expires_in"])
        logger.info("OAuth2 token acquired, expires in %s seconds", data["expires_in"])
        return self._token  # type: ignore[return-value]
