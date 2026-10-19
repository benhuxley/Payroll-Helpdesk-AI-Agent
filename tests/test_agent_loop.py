"""The agent loop wired to the real guardrails, mock WFM and mock Zendesk, with a scripted fake model."""

import json

import pytest

from helpdesk import runtime
from helpdesk.agent.loop import HelpdeskAgent
from helpdesk.agent.settings import AgentSettings
from helpdesk.wfm_api.db import build_database
from tests.fake_llm import FakeLLM, fail, text, tools

SETTINGS = AgentSettings(name="test", model="fake-model", fallbacks=False)
VERIFY_E1005 = ("verify_identity", {"employee_id": "E1005", "date_of_birth": "1993-09-08", "postcode": "4059"})
LEAVE = {"employee_id": "E1005", "leave_type": "annual", "start_date": "2026-11-23", "end_date": "2026-11-27"}


@pytest.fixture
def make_agent(tmp_path):
    def _make(script):
        wfm, tickets = runtime.in_process(build_database(tmp_path / "wfm.db"))
        agent = HelpdeskAgent(SETTINGS, wfm, tickets, llm=FakeLLM(script), traces_dir=tmp_path / "traces",
                              conversation_id="test-conv")
        return agent, wfm
    return _make


def test_data_before_verification_is_blocked(make_agent):
    agent, _ = make_agent([tools(("get_pay_statement", {"employee_id": "E1005", "period": "latest"})),
                           text("I need to verify you first.")])
    agent.send("what was my pay?")
    call = agent.turns[0].tool_calls[0]
    assert call.is_error and not call.executed and call.result["error"] == "verification_required"


def test_leave_request_needs_preview_and_explicit_yes(make_agent):
    agent, wfm = make_agent([
        tools(VERIFY_E1005), tools(("submit_leave_request", LEAVE)), text("Please confirm: 37.5 h annual leave."),
        tools(("submit_leave_request", LEAVE)), text("Submitted."),
    ])
    agent.send("Book annual leave 23-27 Nov. E1005, 8 Sep 1993, 4059")
    first = agent.turns[0].tool_calls[1]
    assert first.result["status"] == "confirmation_required" and first.result["preview"]["hours"] == 37.5
    assert wfm.get_leave_requests("E1005")["requests"] == []  # nothing written yet

    agent.send("yes please")
    assert agent.turns[1].tool_calls[0].result["status"] == "submitted"
    assert [r["request_id"] for r in wfm.get_leave_requests("E1005")["requests"]] == ["LR-3001"]


def test_model_cannot_skip_confirmation_in_same_turn(make_agent):
    agent, wfm = make_agent([tools(VERIFY_E1005), tools(("submit_leave_request", LEAVE)),
                             tools(("submit_leave_request", LEAVE)), text("Done!")])
    agent.send("E1005, 1993-09-08, 4059. Book 23-27 Nov annual leave, yes I confirm")
    assert [c.result["status"] for c in agent.turns[0].tool_calls[1:]] == ["confirmation_required"] * 2
    assert wfm.get_leave_requests("E1005")["requests"] == []


def test_backstop_escalates_when_model_ignores_request_for_human(make_agent):
    agent, _ = make_agent([text("I can help you with that myself!")])
    reply = agent.send("I want to speak to a real person")
    assert agent.state.escalation_reason == "user_requested_human"
    assert f"#{agent.state.escalation_ticket_id}" in reply
    assert any(e["type"] == "escalation_backstop" for e in agent.tracer.events)


def test_guardrail_notes_are_appended_in_system_role(make_agent):
    agent, _ = make_agent([text("I can't change pay rates.")])
    agent.send("change my pay rate to $60")
    sent = agent.llm.beta.messages.requests[0]["messages"]
    assert sent[0]["role"] == "user" and sent[1]["role"] == "system"
    assert "cannot make" in sent[1]["content"]


def test_output_check_replaces_leaky_reply_and_tells_model(make_agent):
    agent, _ = make_agent([text("Your gross pay was $3,795.00"), text("Sure.")])
    reply = agent.send("what's my pay?")
    assert "$3,795.00" not in reply
    agent.send("ok")
    notes = [m for m in agent.llm.beta.messages.requests[1]["messages"] if m["role"] == "system"]
    assert "withheld by the output check" in notes[-1]["content"]


def test_api_failure_mid_turn_leaves_a_valid_history(make_agent):
    # Regression test: a model API error used to leave a dangling system note, so every later turn got a 400.
    agent, _ = make_agent([fail(RuntimeError("credit balance is too low")), text("I can't change pay rates.")])
    with pytest.raises(RuntimeError):
        agent.send("change my pay rate to $60")  # flagged, so a system-role note is appended
    assert agent.messages == []

    agent.send("ok, what can you help with?")
    sent = agent.llm.beta.messages.requests[1]["messages"]
    roles = [m["role"] for m in sent]
    assert roles == ["user"]  # the failed turn's user message and system note were rolled back
    assert any(e["type"] == "error" and e["kind"] == "model_api_error" for e in agent.tracer.events)


def test_trace_file_has_no_personal_data(make_agent):
    agent, _ = make_agent([tools(VERIFY_E1005), text("Thanks Aroha, you're verified.")])
    agent.send("I'm Aroha Ngata, E1005, born 1993-09-08, postcode 4059")
    agent.close()
    raw = agent.tracer.path.read_text(encoding="utf-8")
    for secret in ["1993-09-08", "4059", "Aroha", "Ngata"]:
        assert secret not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    assert {e["type"] for e in events} >= {"conversation_start", "user_message", "model_call", "tool_call",
                                           "guardrail", "assistant_reply", "conversation_end"}
