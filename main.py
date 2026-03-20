"""Entrypoint — delegates to app.main so uvicorn can be pointed at this file."""
from app.main import app  # noqa: F401
