import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings
from app.models import ErrorResponse, HealthResponse, RoutingRequest
from app.services import AuthClient, AuthError, RoutingClient, RoutingConnectionError, RoutingError
from app.utils.jwt_auth import init_jwks, make_jwt_dependency
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

# Build the JWT dependency once — it's a no-op if JWT_JWKS_URI is not set
_verify_jwt = make_jwt_dependency(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_jwks(settings)   # pre-load JWKS keys at startup
    logger.info("vessel-routing-client starting on port %s", settings.port)
    yield
    logger.info("vessel-routing-client shutting down")


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
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def get_health() -> HealthResponse:
    """Liveness / readiness probe — no auth required."""
    return HealthResponse()


@app.post("/route", status_code=200, tags=["routing"])
async def post_route(
    request: Request,
    body: RoutingRequest,
    _claims: Annotated[dict | None, Depends(_verify_jwt)],
) -> JSONResponse:
    """
    Compute a vessel route.

    Requires a valid Bearer JWT in the Authorization header when
    JWT_JWKS_URI is configured.
    """
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    logger.info(json.dumps({
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "correlation_id": correlation_id,
    }))

    start = time.monotonic()
    try:
        result = await _routing_client.compute_route(body.model_dump())
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
