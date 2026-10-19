"""Minimal web chat for the demo: one HTML page plus a JSON chat endpoint.

The agent talks to the mock WFM server over real HTTP (runtime.remote), like a real deployment would.
Each browser session gets its own HelpdeskAgent (and its own trace file). The response includes the trace
events for that turn (already redacted), so the page can show what happened under the hood.
"""

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from helpdesk import config, runtime
from helpdesk.agent.loop import HelpdeskAgent
from helpdesk.agent.settings import load_settings
from helpdesk.wfm_api import seed_data

STATIC = Path(__file__).parent / "static"


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


class ResetIn(BaseModel):
    session_id: str


def create_web_app(agent_config: str | None = None) -> FastAPI:
    settings = load_settings(agent_config or config.AGENT_CONFIG)
    sessions: dict[str, tuple[HelpdeskAgent, threading.Lock]] = {}
    app = FastAPI(title="Payroll helpdesk agent - demo")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        # Synthetic test identities, shown on the page so anyone can try the demo.
        people = [{"employee_id": e["employee_id"], "name": f"{e['first_name']} {e['last_name']}",
                   "date_of_birth": e["date_of_birth"], "postcode": e["postcode"], "position": e["position"]}
                  for e in seed_data.EMPLOYEES]
        return {"agent": settings.name, "model": settings.model, "ticketing": config.TICKETING_BACKEND,
                "as_of": config.AS_OF_DATE.isoformat(), "test_identities": people}

    @app.post("/api/chat")
    def chat(body: ChatIn):
        if not body.message.strip():
            raise HTTPException(422, "empty message")
        session_id = body.session_id or uuid.uuid4().hex[:12]
        if session_id not in sessions:
            wfm, tickets = runtime.remote()
            agent = HelpdeskAgent(settings, wfm, tickets, conversation_id=f"web-{session_id}")
            sessions[session_id] = (agent, threading.Lock())
        agent, lock = sessions[session_id]
        with lock:
            first_event = len(agent.tracer.events)
            reply = agent.send(body.message.strip())
            events = agent.tracer.events[first_event:]
        return {
            "session_id": session_id,
            "reply": reply,
            "events": events,
            "state": {"verified": agent.state.verified_employee_id is not None,
                      "escalation_ticket_id": agent.state.escalation_ticket_id,
                      "escalation_reason": agent.state.escalation_reason,
                      "ticket_ids": agent.state.ticket_ids,
                      "leave_requests": agent.state.submitted_leave_requests},
            "trace_file": str(agent.tracer.path),
        }

    @app.post("/api/reset")
    def reset(body: ResetIn):
        entry = sessions.pop(body.session_id, None)
        if entry:
            entry[0].close()
        return {"ok": True}

    return app
