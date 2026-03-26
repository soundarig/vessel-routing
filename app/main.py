import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.models import HealthResponse
from app.models.ports import PortResponse, PortsPageResponse
from app.services import AuthClient, AuthError, RoutingClient, RoutingConnectionError, RoutingError
from app.services.ports_client import PortsClient
from app.utils.jwt_auth import create_access_token, make_jwt_dependency, verify_credentials
from app.utils.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup — validate config, wire singletons
# ---------------------------------------------------------------------------
try:
    settings = Settings()
except ValidationError as exc:
    missing = [e["loc"] for e in exc.errors()]
    logger.error("Missing required environment variables: %s", missing)
    sys.exit(1)

_auth_client = AuthClient(settings)
_routing_client = RoutingClient(_auth_client, settings)
_verify_jwt = make_jwt_dependency(settings)
_ports_client = (
    PortsClient(
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        port=settings.db_port,
    )
    if settings.db_host
    else None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vessel-routing-client starting on port %s", settings.port)
    yield
    logger.info("vessel-routing-client shutting down")
    if _ports_client is not None:
        _ports_client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="vessel-routing-client",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def get_health() -> HealthResponse:
    """Liveness / readiness probe — no auth required."""
    return HealthResponse()


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def login(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> TokenResponse:
    """
    Exchange username + password for a Bearer JWT.

    Send as application/x-www-form-urlencoded:
        username=<user>&password=<pass>
    """
    if not verify_credentials(username, password, settings):
        logger.warning("Failed login attempt for user '%s'", username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(username, settings)
    logger.info("Token issued for user '%s'", username)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@app.post("/route", status_code=200, tags=["routing"])
async def post_route(
    request: Request,
    _claims: Annotated[dict, Depends(_verify_jwt)],
) -> JSONResponse:
    """
    Compute a vessel route.

    Accepts the raw ABB vessel routing JSON payload and forwards it directly
    to the WebSocket API. Requires a valid Bearer JWT in the Authorization header.
    Obtain one via POST /auth/token.
    """
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    logger.info(json.dumps({
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "correlation_id": correlation_id,
    }))

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Invalid JSON body"})

    start = time.monotonic()
    try:
        result = await _routing_client.compute_route(body)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info(json.dumps({
            "event": "response",
            "correlation_id": correlation_id,
            "status": 200,
            "duration_ms": duration_ms,
        }))
        return JSONResponse(
            content=result,
            headers={"X-Correlation-ID": correlation_id},
        )

    except AuthError as exc:
        logger.error(json.dumps({"event": "auth_error", "correlation_id": correlation_id,
                                  "error": str(exc)}))
        return JSONResponse(
            status_code=502,
            content={"detail": "Authentication with upstream service failed"},
            headers={"X-Correlation-ID": correlation_id},
        )

    except (RoutingConnectionError, RoutingError) as exc:
        logger.error(json.dumps({"event": "routing_error", "correlation_id": correlation_id,
                                  "error": str(exc)}))
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc)},
            headers={"X-Correlation-ID": correlation_id},
        )

    except Exception:
        logger.exception(json.dumps({"event": "unhandled_error",
                                      "correlation_id": correlation_id}))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={"X-Correlation-ID": correlation_id},
        )


@app.get("/ports/search", response_model=list[PortResponse], tags=["ports"])
async def search_ports(
    _claims: Annotated[dict, Depends(_verify_jwt)],
    q: str,
    limit: int = 100,
) -> list[PortResponse]:
    """
    Search active ports by name, port code, or country code.
    Requires a valid Bearer JWT in the Authorization header.

    - **q**: search string (matched against port name, port code, country code)
    - **limit**: max results to return (default: 20, max: 100)
    """
    if _ports_client is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    try:
        results = await _ports_client.search_ports(q.strip(), limit=limit)
        return results
    except Exception as exc:
        logger.error("Failed to search ports: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to search ports from database")


@app.get("/ports", response_model=PortsPageResponse, tags=["ports"])
async def get_ports(
    _claims: Annotated[dict, Depends(_verify_jwt)],
    page: int = 1,
    page_size: int = 50
) -> PortsPageResponse:
    """
    Fetch paginated active ports with latitude and longitude.
    Requires a valid Bearer JWT in the Authorization header.

    - **page**: page number (default: 1)
    - **page_size**: results per page (default: 50, max: 200)
    """
    if _ports_client is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if not 1 <= page_size <= 200:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 200")
    try:
        result = await _ports_client.get_ports(page=page, page_size=page_size)
        return result
    except Exception as exc:
        logger.error("Failed to fetch ports: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch ports from database")
