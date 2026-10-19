"""A tiny Zendesk-compatible ticketing mock.

It implements the same endpoint paths and JSON shapes as the parts of the Zendesk Tickets API we use
(POST /api/v2/tickets.json, GET /api/v2/tickets/{id}.json). That means the *same* ZendeskClient code
talks to this mock in CI and to a real Zendesk trial in the demo. Only the base URL and credentials change.
"""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from helpdesk.wfm_api.db import connect

router = APIRouter(prefix="/zendesk/api/v2")

PRIORITIES = {"low", "normal", "high", "urgent"}
TYPES = {"question", "incident", "problem", "task"}


class Comment(BaseModel):
    body: str
    public: bool = False


class TicketIn(BaseModel):
    subject: str
    comment: Comment
    priority: str = "normal"
    type: str = "question"
    tags: list[str] = []
    external_id: str | None = None
    custom_fields: list[dict] = []


class TicketEnvelope(BaseModel):
    ticket: TicketIn


def _require_auth(authorization: str | None) -> None:
    # Zendesk uses HTTP Basic auth ("{email}/token:{api_token}"). The mock only checks it is present.
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail={"error": "Couldn't authenticate you"})


def _ticket_json(row, request: Request) -> dict:
    return {
        "id": row["id"], "url": str(request.url_for("show_ticket", ticket_id=row["id"])),
        "subject": row["subject"], "description": row["body"], "priority": row["priority"],
        "type": row["type"], "status": row["status"], "tags": json.loads(row["tags"]),
        "external_id": row["external_id"], "custom_fields": json.loads(row["custom_fields"]),
        "created_at": row["created_at"],
    }


@router.post("/tickets.json", status_code=201)
def create_ticket(envelope: TicketEnvelope, request: Request, authorization: str | None = Header(default=None)):
    _require_auth(authorization)
    t = envelope.ticket
    if t.priority not in PRIORITIES or t.type not in TYPES:
        raise HTTPException(status_code=422, detail={"error": "RecordInvalid",
                                                     "description": "priority or type is invalid"})
    conn = connect(request.app.state.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO tickets (subject, body, priority, type, status, tags, external_id, custom_fields,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (t.subject, t.comment.body, t.priority, t.type, "new", json.dumps(t.tags), t.external_id,
             json.dumps(t.custom_fields), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")))
        conn.commit()
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ticket": _ticket_json(row, request)}
    finally:
        conn.close()


@router.get("/tickets/{ticket_id}.json", name="show_ticket")
def show_ticket(ticket_id: int, request: Request, authorization: str | None = Header(default=None)):
    _require_auth(authorization)
    conn = connect(request.app.state.db_path)
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "RecordNotFound"})
        return {"ticket": _ticket_json(row, request)}
    finally:
        conn.close()


@router.get("/tickets.json")
def list_tickets(request: Request, authorization: str | None = Header(default=None)):
    _require_auth(authorization)
    conn = connect(request.app.state.db_path)
    try:
        rows = conn.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
        return {"tickets": [_ticket_json(r, request) for r in rows]}
    finally:
        conn.close()
