"""
Inbound authentication utilities.

Flow:
  1. Caller POSTs username + password to POST /auth/token
  2. Service verifies credentials against API_USERNAME / API_PASSWORD_HASH (bcrypt)
  3. Service issues a signed HS256 JWT valid for JWT_EXPIRE_MINUTES
  4. Caller includes the JWT as  Authorization: Bearer <token>  on subsequent requests
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import Settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_credentials(username: str, password: str, settings: Settings) -> bool:
    """Return True if username matches and password verifies against the stored hash."""
    if username != settings.api_username:
        return False
    try:
        return bcrypt.checkpw(password.encode(), settings.api_password_hash.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Token issuance
# ---------------------------------------------------------------------------

def create_access_token(username: str, settings: Settings) -> str:
    """Issue a signed HS256 JWT for the given username."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# Token validation dependency
# ---------------------------------------------------------------------------

def make_jwt_dependency(settings: Settings):
    """Returns a FastAPI dependency that validates inbound Bearer JWTs."""

    async def _verify_jwt(
        credentials: Annotated[HTTPAuthorizationCredentials, Security(_bearer_scheme)],
    ) -> dict:
        token = credentials.credentials
        try:
            claims = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError as exc:
            logger.warning("JWT validation failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return claims

    return _verify_jwt
