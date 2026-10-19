"""Wiring: build the WFM and ticketing clients for a given environment.

  in_process(db_path)  - no servers. The FastAPI app is called in-process (CLI, tests, evals).
  remote()             - talk to a running mock WFM server over real HTTP (web demo).
Ticketing goes to the mock unless TICKETING_BACKEND=zendesk.
"""

import base64
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from helpdesk import config
from helpdesk.integrations.ticketing import ZendeskClient, zendesk_from_env
from helpdesk.integrations.wfm_client import WFMClient
from helpdesk.wfm_api.app import create_app

MOCK_ZENDESK_AUTH = ("demo@kestrelbay.example/token", "mock-token")


def _basic_auth_header(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def in_process(db_path: Path | str, ticketing_backend: str = "mock") -> tuple[WFMClient, ZendeskClient]:
    app = create_app(db_path, api_key=config.WFM_API_KEY)
    wfm = WFMClient(TestClient(app, headers={"X-API-Key": config.WFM_API_KEY}))
    if ticketing_backend == "zendesk":
        return wfm, zendesk_from_env()
    tickets_http = TestClient(app, base_url="http://testserver/zendesk",
                              headers=_basic_auth_header(*MOCK_ZENDESK_AUTH))
    return wfm, ZendeskClient(tickets_http, backend="mock")


def remote(ticketing_backend: str | None = None) -> tuple[WFMClient, ZendeskClient]:
    backend = ticketing_backend or config.TICKETING_BACKEND
    wfm = WFMClient(httpx.Client(base_url=config.WFM_BASE_URL, headers={"X-API-Key": config.WFM_API_KEY},
                                 timeout=20))
    if backend == "zendesk":
        return wfm, zendesk_from_env()
    tickets_http = httpx.Client(base_url=f"{config.WFM_BASE_URL}/zendesk", auth=MOCK_ZENDESK_AUTH, timeout=20)
    return wfm, ZendeskClient(tickets_http, backend="mock")
