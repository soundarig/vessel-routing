"""Entrypoint — delegates to app.main so uvicorn can be pointed at this file."""
import uvicorn

from app.main import app  # noqa: F401

if __name__ == "__main__":
    # Start the FastAPI application in debug mode
    uvicorn.run("main:app", host="0.0.0.0", port=8000)