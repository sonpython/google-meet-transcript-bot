"""Runs the FastAPI app; drop-in replacement for the old stdlib server."""

import os

import uvicorn

from src.web_app.app import create_app


def serve_forever() -> None:
    uvicorn.run(
        create_app(),
        host=os.getenv("HEALTH_HOST", "0.0.0.0"),
        port=int(os.getenv("HEALTH_PORT", "8080")),
        log_level="warning",
    )
