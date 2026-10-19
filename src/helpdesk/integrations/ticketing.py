"""Zendesk ticketing client.

One client, two backends:
  - mock:    the Zendesk-compatible endpoint inside the mock WFM server (used by tests, evals and CI)
  - zendesk: a real Zendesk account (e.g. a free trial), using an API token

Zendesk API reference: POST /api/v2/tickets.json with {"ticket": {...}}, Basic auth "{email}/token:{token}".
We deliberately send no `requester` (so no Zendesk end-users get created for synthetic people) and
identify the employee by `external_id` and tags instead.
"""

import httpx

from helpdesk import config


class TicketingError(Exception):
    pass


class ZendeskClient:
    def __init__(self, http: httpx.Client, backend: str):
        self.http = http
        self.backend = backend  # "mock" or "zendesk", recorded in traces

    def create_ticket(self, subject: str, body: str, priority: str, ticket_type: str, tags: list[str],
                      external_id: str | None) -> dict:
        payload = {"ticket": {
            "subject": subject,
            "comment": {"body": body, "public": False},  # internal note: not emailed to anyone
            "priority": priority,
            "type": ticket_type,
            "tags": tags,
            "external_id": external_id,
        }}
        response = self.http.post("/api/v2/tickets.json", json=payload)
        if response.status_code != 201:
            raise TicketingError(f"Zendesk returned {response.status_code}: {response.text[:300]}")
        ticket = response.json()["ticket"]
        return {"ticket_id": ticket["id"], "status": ticket["status"], "priority": ticket["priority"],
                "backend": self.backend}


def zendesk_from_env() -> ZendeskClient:
    """A client for a real Zendesk account, configured from environment variables."""
    missing = [name for name, value in [("ZENDESK_SUBDOMAIN", config.ZENDESK_SUBDOMAIN),
                                        ("ZENDESK_EMAIL", config.ZENDESK_EMAIL),
                                        ("ZENDESK_API_TOKEN", config.ZENDESK_API_TOKEN)] if not value]
    if missing:
        raise TicketingError(f"TICKETING_BACKEND=zendesk but these are not set: {', '.join(missing)}")
    http = httpx.Client(base_url=f"https://{config.ZENDESK_SUBDOMAIN}.zendesk.com",
                        auth=(f"{config.ZENDESK_EMAIL}/token", config.ZENDESK_API_TOKEN), timeout=20)
    return ZendeskClient(http, backend="zendesk")
