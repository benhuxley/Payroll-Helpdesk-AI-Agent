"""The agent loop: one call to `send()` handles one user message.

    user message
      -> input screen (guardrail notes added in the system role)
      -> model call  <-----------------------------+
      -> tool calls? -> executor (policy, gate) ---+   (repeat until the model answers)
      -> escalation backstop
      -> output check
      -> reply to user
Every step is written to the trace.

Why a hand-written loop instead of the SDK's tool runner? Every tool call has to pass through our policy
layer and be traced with timings, and the confirmation gate needs the user's latest words. Owning the
~60 lines of loop keeps that one choke point obvious and easy to audit.

The message history is append-only. We never edit earlier messages (that would break prompt caching and
Claude's preserved thinking). Guardrail notes are *appended* as system-role messages after the user message.
"""

import time
import uuid
from dataclasses import dataclass, field

import anthropic

from helpdesk import config
from helpdesk.agent.settings import AgentSettings
from helpdesk.agent.state import ConversationState
from helpdesk.agent.tools import TOOL_DEFINITIONS, ToolExecutor
from helpdesk.guardrails import escalation, input_screen, output_check
from helpdesk.guardrails.redaction import Redactor
from helpdesk.integrations.ticketing import TicketingError, ZendeskClient
from helpdesk.integrations.wfm_client import WFMClient
from helpdesk.tracing.tracer import Tracer

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_REPLY = "Sorry, I can't help with that one. I can pass your question to the payroll team if you like."
STEP_LIMIT_REPLY = ("Sorry, I'm having trouble finishing that. I've noted it, and you can ask me to pass it to "
                    "the payroll team.")


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    result: dict
    is_error: bool
    executed: bool
    decisions: list[dict]


@dataclass
class TurnRecord:
    """What happened in one user turn, kept in memory (unredacted) for the eval harness. Never written to disk."""

    user_text: str
    reply: str = ""
    model_reply: str = ""  # what the model wrote, before the output check
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    stop_reason: str | None = None


class HelpdeskAgent:
    def __init__(self, settings: AgentSettings, wfm: WFMClient, tickets: ZendeskClient,
                 llm: anthropic.Anthropic | None = None, traces_dir=config.TRACES_DIR,
                 conversation_id: str | None = None):
        self.settings = settings
        self.llm = llm or anthropic.Anthropic(max_retries=4)
        self.conversation_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
        self.state = ConversationState(conversation_id=self.conversation_id)
        self.directory = wfm.directory()
        self.redactor = Redactor(self.directory)
        self.tracer = Tracer(self.conversation_id, traces_dir, self.redactor)
        self.executor = ToolExecutor(wfm, tickets, self.state, self.redactor)
        self.system_prompt = settings.system_prompt
        self.messages: list[dict] = []
        self.turns: list[TurnRecord] = []
        self._notes_for_next_turn: list[str] = []
        self.tracer.log("conversation_start", agent_version=settings.name, model=settings.model,
                        effort=settings.effort, system_prompt_file=settings.system_prompt_file,
                        ticketing_backend=tickets.backend)

    # --- public -------------------------------------------------------------------------------------
    def send(self, user_text: str) -> str:
        self.state.user_turn += 1
        turn = TurnRecord(user_text=user_text)
        self.turns.append(turn)
        self.tracer.log("user_message", turn=self.state.user_turn, text=user_text)

        # Layer 1: input screen -> operator notes
        flags = input_screen.screen_user_message(user_text, self.state.verified_employee_id)
        for decision in flags:
            self._record_decision(turn, decision)
        carried_notes = self._notes_for_next_turn
        notes = carried_notes + [d.note_for_model for d in flags if d.note_for_model]
        self._notes_for_next_turn = []

        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        if notes:
            self.messages.append({"role": "system", "content": "\n".join(notes)})

        try:
            model_reply = self._run_model_loop(turn, user_text)
        except Exception as exc:
            # The model API failed mid-turn (outage, rate limit, no credit...). Drop this turn's unfinished
            # messages so the history stays valid (a system note must be followed by an assistant turn),
            # keep any carried-over notes for next time, and let the caller show an error.
            del self.messages[checkpoint:]
            self._notes_for_next_turn = carried_notes
            self.tracer.log("error", turn=self.state.user_turn, kind="model_api_error",
                            detail=f"{type(exc).__name__}: {str(exc)[:300]}")
            raise

        # Layer 5: escalation backstop
        required = escalation.mandatory_reason([d.rule for d in flags], self.state)
        backstop = escalation.backstop(required, self.state)
        if backstop:
            self._record_decision(turn, backstop)
            model_reply = self._backstop_escalate(required, user_text, model_reply)

        # Layer 4: output check
        everything_user_typed = "\n".join(t.user_text for t in self.turns)
        reply, out_decisions = output_check.check_reply(model_reply, self.state.verified_employee_id,
                                                        self.directory, everything_user_typed)
        for decision in out_decisions:
            self._record_decision(turn, decision)
        if reply != model_reply:
            rules = ", ".join(d.rule for d in out_decisions)
            self._notes_for_next_turn.append(
                f"Platform note: your previous reply was withheld by the output check ({rules}). The user saw "
                f"this instead: \"{reply}\"")

        turn.model_reply, turn.reply = model_reply, reply
        self.tracer.log("assistant_reply", turn=self.state.user_turn, text=reply,
                        replaced_by_output_check=reply != model_reply)
        return reply

    def close(self) -> None:
        self.tracer.log("conversation_end", turns=self.state.user_turn,
                        verified=self.state.verified_employee_id is not None,
                        escalation_ticket_id=self.state.escalation_ticket_id,
                        escalation_reason=self.state.escalation_reason, ticket_ids=self.state.ticket_ids,
                        leave_requests_submitted=self.state.submitted_leave_requests)

    # --- the loop -----------------------------------------------------------------------------------
    def _run_model_loop(self, turn: TurnRecord, user_text: str) -> str:
        for step in range(1, self.settings.max_steps + 1):
            response = self._call_model(step)
            self.messages.append({"role": "assistant", "content": response.content})
            turn.stop_reason = response.stop_reason

            if response.stop_reason == "refusal":
                return REFUSAL_REPLY

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                return text or STEP_LIMIT_REPLY

            # Run every tool call, then return all results together in one user message.
            results = []
            for block in tool_uses:
                outcome = self.executor.run(block.name, block.input, user_text)
                decisions = [d.to_dict() for d in outcome.decisions]
                turn.tool_calls.append(ToolCallRecord(block.name, dict(block.input), outcome.content,
                                                      outcome.is_error, outcome.executed, decisions))
                turn.decisions.extend(decisions)
                self.tracer.log("tool_call", turn=self.state.user_turn, step=step, name=block.name,
                                input=block.input, result=outcome.content, is_error=outcome.is_error,
                                executed=outcome.executed, latency_ms=outcome.latency_ms, decisions=decisions)
                results.append(outcome.as_tool_result(block.id))
            self.messages.append({"role": "user", "content": results})

        self.tracer.log("error", turn=self.state.user_turn, kind="step_limit", max_steps=self.settings.max_steps)
        return STEP_LIMIT_REPLY

    def _call_model(self, step: int):
        params = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": self.system_prompt,
            "tools": TOOL_DEFINITIONS,
            "messages": self.messages,
            # Thinking is always on for current models; effort controls how much. "summarized" gives us a
            # readable summary of the reasoning, which goes (redacted) into the trace for debugging.
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.settings.effort},
            # Automatic prompt caching: the system prompt, tools and history are re-read from cache each step.
            "cache_control": {"type": "ephemeral"},
        }
        if self.settings.fallbacks:
            # If a safety classifier declines a request, the API retries it on a fallback model server-side.
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"

        started = time.perf_counter()
        response = self.llm.beta.messages.create(**params)
        latency_ms = int((time.perf_counter() - started) * 1000)

        usage = response.usage
        self.tracer.log(
            "model_call", turn=self.state.user_turn, step=step, model_requested=self.settings.model,
            model_served=response.model, stop_reason=response.stop_reason, latency_ms=latency_ms,
            usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                   "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
                   "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0},
            thinking=[b.thinking for b in response.content if b.type == "thinking" and b.thinking],
            text=[b.text for b in response.content if b.type == "text"],
            tool_uses=[b.name for b in response.content if b.type == "tool_use"],
            request_id=getattr(response, "_request_id", None),
        )
        return response

    # --- helpers ------------------------------------------------------------------------------------
    def _backstop_escalate(self, reason: str, user_text: str, model_reply: str) -> str:
        try:
            ticket = self.executor.escalate(
                reason=reason, summary="Automatic handoff by helpdesk guardrail",
                details=f"Mandatory escalation rule fired ({reason}). Last user message: {user_text}",
                urgency="high")
        except TicketingError as exc:
            self.tracer.log("error", turn=self.state.user_turn, kind="backstop_ticket_failed", detail=str(exc))
            return model_reply
        self.tracer.log("escalation_backstop", turn=self.state.user_turn, reason=reason,
                        ticket_id=ticket["ticket_id"])
        self._notes_for_next_turn.append(
            f"Platform note: the platform handed this conversation to a payroll officer (ticket "
            f"#{ticket['ticket_id']}, reason {reason}). Don't escalate again.")
        return (f"{model_reply}\n\nI've also passed this to a payroll officer (ticket #{ticket['ticket_id']}). "
                "They'll be in touch within 4 business hours.").strip()

    def _record_decision(self, turn: TurnRecord, decision) -> None:
        record = decision.to_dict()
        turn.decisions.append(record)
        self.tracer.log("guardrail", turn=self.state.user_turn, **record)
