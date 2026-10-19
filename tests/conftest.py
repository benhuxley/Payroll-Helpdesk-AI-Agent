import pytest
from fastapi.testclient import TestClient

from helpdesk.wfm_api.app import create_app
from helpdesk.wfm_api.db import build_database

API_KEY = "test-key"


@pytest.fixture
def wfm_app(tmp_path):
    """A fresh mock WFM app on its own throwaway database (clean state for every test)."""
    db_path = build_database(tmp_path / "wfm.db")
    return create_app(db_path, api_key=API_KEY)


@pytest.fixture
def wfm_http(wfm_app):
    """An httpx-compatible client that calls the app in-process (no network, no port)."""
    return TestClient(wfm_app, headers={"X-API-Key": API_KEY})
