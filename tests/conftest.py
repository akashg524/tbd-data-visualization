"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.engine import analytics_engine
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def _init_engine():
    """Initialize the analytics engine once for the test session."""
    analytics_engine.initialize()
    yield
    analytics_engine.shutdown()


@pytest.fixture()
def client():
    """FastAPI test client."""
    application = create_app()
    with TestClient(application) as c:
        yield c
