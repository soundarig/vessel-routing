"""
Inbound JWT authentication dependency for FastAPI.

Validates Bearer tokens against a JWKS URI (RS256/ES256).
The JWKS is fetched once at startup and cached in memory.
"""
import logging
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from app.config import Settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)

# Module-level JWKS cache: {kid: key_dict}
_jwks_cache: dict[str, dict] = {}


async def _load_jwks(jwks_uri: str) -> None:
    """Fetch JWKS from the identity provider and populate the cache."""
    global _jwks_cache
    logger.info("Loading JWKS from %s", jwks_uri)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_uri)
        response.raise_for_status()
    keys = response.json().get("keys", [])
    _jwks_cache = {k["kid"]: k for k in keys if "kid" in k}
    logger.info("Loaded %d keys from JWKS", len(_jwks_cache))


async def init_jwks(settings: Settings) -> None:
    """Call this at application startup to pre-load the JWKS."""
    if settings.jwt_jwks_uri:
        await _load_jwks(settings.jwt_jwks_uri)
    else:
        logger.warning(
            "JWT_JWKS_URI is not set — inbound JWT validation is DISABLED. "
            "Set JWT_JWKS_URI, JWT_AUDIENCE, and JWT_ISSUER to enable it."
        )


def _get_signing_key(token: str, settings: Settings) -> str:
    """Extract the matching public key from the JWKS cache for the token's kid."""
    try:
        headers = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token header") from exc

    kid = headers.get("kid")
    if not kid or kid not in _jwks_cache:
        raise HTTPException(
            status_code=401,
            detail="Token signing key not found — JWKS may need refreshing",
        )
    return _jwks_cache[kid]


def make_jwt_dependency(settings: Settings):
    """
    Returns a FastAPI dependency that validates inbound JWTs.

    If JWT_JWKS_URI is not configured the dependency is a no-op (open),
    so the service can start without auth during local development.
    """
    if not settings.jwt_jwks_uri:
        # Auth disabled — return a passthrough dependency
        async def _no_auth():
            return None
        return _no_auth

    async def _verify_jwt(
        credentials: Annotated[HTTPAuthorizationCredentials, Security(_bearer_scheme)],
    ) -> dict:
        token = credentials.credentials
        key = _get_signing_key(token, settings)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=settings.jwt_algorithms,
                audience=settings.jwt_audience or None,
                issuer=settings.jwt_issuer or None,
                options={"verify_aud": bool(settings.jwt_audience)},
            )
        except JWTError as exc:
            logger.warning("JWT validation failed: %s", exc)
            raise HTTPException(status_code=401, detail=f"Token validation failed: {exc}")

        return claims

    return _verify_jwt
