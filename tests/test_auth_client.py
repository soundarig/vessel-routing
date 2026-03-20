"""Unit tests for AuthClient token caching and error handling."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services.auth_client import AuthClient, AuthError


@pytest.fixture
def settings():
    return Settings(
        oauth_client_id="test-id",
        oauth_client_secret="test-secret",
    )


@pytest.fixture
def auth_client(settings):
    return AuthClient(settings)


@pytest.mark.asyncio
async def test_fetches_token_on_first_call(auth_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    with patch("app.services.auth_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        token = await auth_client.get_token()

    assert token == "tok123"


@pytest.mark.asyncio
async def test_returns_cached_token_without_new_request(auth_client):
    auth_client._token = "cached-tok"
    auth_client._expires_at = time.time() + 3600  # valid for 1 hour

    with patch("app.services.auth_client.httpx.AsyncClient") as mock_cls:
        token = await auth_client.get_token()
        mock_cls.assert_not_called()

    assert token == "cached-tok"


@pytest.mark.asyncio
async def test_refreshes_expired_token(auth_client):
    auth_client._token = "old-tok"
    auth_client._expires_at = time.time() - 1  # already expired

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok", "expires_in": 3600}

    with patch("app.services.auth_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        token = await auth_client.get_token()

    assert token == "new-tok"


@pytest.mark.asyncio
async def test_raises_auth_error_on_non_200(auth_client):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("app.services.auth_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        with pytest.raises(AuthError) as exc_info:
            await auth_client.get_token()

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalidate_forces_refresh(auth_client):
    auth_client._token = "valid-tok"
    auth_client._expires_at = time.time() + 3600

    auth_client.invalidate()
    assert not auth_client._is_valid()
