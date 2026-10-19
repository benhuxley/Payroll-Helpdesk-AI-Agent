"""Shared settings. Everything that can change between environments comes from environment variables."""

import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The synthetic world is frozen on this date so that evals are reproducible.
# All pay periods, rosters and leave requests in the seed data are built around it.
AS_OF_DATE = date(2026, 10, 19)  # Monday

DATA_DIR = REPO_ROOT / "data"
TRACES_DIR = Path(os.environ.get("TRACES_DIR", REPO_ROOT / "traces"))

WFM_BASE_URL = os.environ.get("WFM_BASE_URL", "http://127.0.0.1:8001")
WFM_API_KEY = os.environ.get("WFM_API_KEY", "dev-wfm-key")
WFM_DB_PATH = Path(os.environ.get("WFM_DB_PATH", DATA_DIR / "wfm.db"))

AGENT_CONFIG = os.environ.get("AGENT_CONFIG", str(REPO_ROOT / "configs" / "agent_v2.yaml"))

TICKETING_BACKEND = os.environ.get("TICKETING_BACKEND", "mock")  # "mock" or "zendesk"
ZENDESK_SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "")
ZENDESK_EMAIL = os.environ.get("ZENDESK_EMAIL", "")
ZENDESK_API_TOKEN = os.environ.get("ZENDESK_API_TOKEN", "")
