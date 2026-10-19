"""Tool definitions (what the model sees) and the executor (what actually runs).

Every tool call goes through ToolExecutor.run(), which is the single choke point:
    access policy check -> (confirmation gate for writes) -> WFM / ticketing call -> result back to the model

Tool descriptions say *when* to call each tool, not just what it does. Claude relies on them heavily.
"strict": True makes the API guarantee the arguments match the schema.
"""

import json
import time
from dataclasses import dataclass, field

from helpdesk.agent.state import ConversationState
from helpdesk.guardrails import access_policy, confirmation
from helpdesk.guardrails.decisions import GuardrailDecision
from helpdesk.guardrails.escalation import REASONS
from helpdesk.guardrails.redaction import Redactor
from helpdesk.integrations.ticketing import TicketingError, ZendeskClient
from helpdesk.integrations.wfm_client import WFMClient, WFMError

DATE = {"type": "string", "description": "Date in YYYY-MM-DD format."}
EMPLOYEE_ID = {"type": "string", "description": "The verified employee's ID, e.g. E1234."}


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {"type": "object", "properties": properties, "required": list(properties),
                         "additionalProperties": False},
    }


TOOL_DEFINITIONS = [
    _tool("verify_identity",
          "Verify the user's identity against the HR system. Call this as soon as the user has given their "
          "employee ID, date of birth and home postcode, and before using any tool that returns personal data. "
          "Returns verified true/false. It never says which detail was wrong.",
          {"employee_id": EMPLOYEE_ID,
           "date_of_birth": {"type": "string", "description": "Date of birth in YYYY-MM-DD format."},
           "postcode": {"type": "string", "description": "Home postcode (4 digits)."}}),
    _tool("get_pay_statement",
          "Get a pay statement (payslip) with every pay line: code, hours, rate and amount, plus gross, tax, "
          "net and super. Also lists the other available statements. Call this for any question about pay, "
          "payslips, pay amounts or deductions. To explain a pay amount, also call get_timecards for the "
          "same period and reconcile them.",
          {"employee_id": EMPLOYEE_ID,
           "period": {"type": "string",
                      "description": "'latest' for the most recent pay statement, or any date (YYYY-MM-DD) "
                                     "inside the pay period you want."}}),
    _tool("get_timecards",
          "Get timecards day by day: rostered shift, clock in/out punches, pay code, paid hours, overtime "
          "and when it was approved, exceptions (e.g. missed punches), manual edits, public holidays, plus "
          "the pay period dates and timecard approval cutoff. Call this to explain or check pay. Use the pay "
          "statement's period_start and period_end as the date range.",
          {"employee_id": EMPLOYEE_ID, "start_date": DATE, "end_date": DATE}),
    _tool("get_roster",
          "Get rostered (scheduled) shifts in a date range: date, start and end time, location. Call this for "
          "questions about upcoming or past rostered shifts.",
          {"employee_id": EMPLOYEE_ID, "start_date": DATE, "end_date": DATE}),
    _tool("get_leave_balance",
          "Get leave balances (annual, personal/carer's, long service) in hours, including hours tied up in "
          "pending requests, plus all leave requests and their status (pending/approved/declined) and approver. "
          "Call this for questions about leave balances or the status of a leave request, and before submitting "
          "a new request.",
          {"employee_id": EMPLOYEE_ID}),
    _tool("submit_leave_request",
          "Submit a leave request for the verified employee. The first call does NOT submit anything: it returns "
          "a preview (hours, approver) that you must show the user, asking them to confirm. Only after the user "
          "explicitly says yes, call it again with exactly the same arguments to submit. Requests go to the "
          "employee's manager for approval; this tool cannot approve leave.",
          {"employee_id": EMPLOYEE_ID,
           "leave_type": {"type": "string", "enum": ["annual", "personal", "long_service"]},
           "start_date": DATE, "end_date": DATE}),
    _tool("create_ticket",
          "Create a ticket for the payroll team for routine follow-up work that doesn't need a person right now, "
          "e.g. a missed punch that needs a manager correction, or a question you can't fully answer from the "
          "data. Only for verified users. Don't use this for payroll errors, upset users or requests for a "
          "person: use escalate_to_human instead.",
          {"category": {"type": "string",
                        "enum": ["timecard_correction", "pay_query_follow_up", "leave_query", "other"]},
           "summary": {"type": "string", "description": "One line: what needs doing."},
           "details": {"type": "string",
                       "description": "Evidence for the payroll officer: dates, hours, pay codes, amounts, what "
                                      "the employee said. No date of birth or postcode."},
           "priority": {"type": "string", "enum": ["low", "normal", "high"]}}),
    _tool("escalate_to_human",
          "Hand the conversation to a payroll officer (creates a priority ticket). Call this when: you find a "
          "likely payroll error (the employee was paid incorrectly); the user asks for a person; the user is "
          "very upset or in financial hardship; you can't explain something from the data or aren't confident "
          "(low_confidence); verification has failed 3 times. Works for unverified users too.",
          {"reason": {"type": "string", "enum": REASONS},
           "summary": {"type": "string", "description": "One line for the payroll officer."},
           "details": {"type": "string",
                       "description": "What you found: dates, hours, pay codes, expected vs paid amounts, and "
                                      "what the user asked. No date of birth or postcode."},
           "urgency": {"type": "string", "enum": ["normal", "high", "urgent"]}}),
]

TICKET_TYPE = {"timecard_correction": "task", "pay_query_follow_up": "question", "leave_query": "question",
               "other": "question"}
SLA = {"low": "within 3 business days", "normal": "within 1 business day", "high": "within 4 business hours",
       "urgent": "within 2 business hours"}


@dataclass
class ToolOutcome:
    content: dict
    is_error: bool = False
    decisions: list[GuardrailDecision] = field(default_factory=list)
    latency_ms: int = 0
    executed: bool = False  # True if the tool really ran against a backend system

    def as_tool_result(self, tool_use_id: str) -> dict:
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(self.content),
                "is_error": self.is_error}


class ToolExecutor:
    def __init__(self, wfm: WFMClient, tickets: ZendeskClient, state: ConversationState, redactor: Redactor):
        self.wfm = wfm
        self.tickets = tickets
        self.state = state
        self.redactor = redactor

    def run(self, name: str, tool_input: dict, latest_user_text: str) -> ToolOutcome:
        started = time.perf_counter()
        decision = access_policy.check_tool_call(name, tool_input, self.state)
        if decision.action == "block":
            outcome = ToolOutcome({"error": decision.rule, "message": decision.detail}, is_error=True,
                                  decisions=[decision])
        else:
            handler = getattr(self, f"_{name}")
            try:
                outcome = handler(tool_input, latest_user_text)
            except WFMError as exc:
                outcome = ToolOutcome({"error": "wfm_api_error", "status": exc.status_code, "detail": exc.detail},
                                      is_error=True)
            except TicketingError as exc:
                outcome = ToolOutcome({"error": "ticketing_error", "detail": str(exc)}, is_error=True)
            outcome.decisions.insert(0, decision)
        outcome.latency_ms = int((time.perf_counter() - started) * 1000)
        return outcome

    # --- handlers: one per tool ----------------------------------------------------------------
    def _verify_identity(self, args: dict, _: str) -> ToolOutcome:
        result = self.wfm.verify_identity(args["employee_id"].strip().upper(), args["date_of_birth"],
                                          args["postcode"])
        if result["verified"]:
            self.state.verified_employee_id = result["employee_id"]
            self.state.verified_first_name = result["first_name"]
            return ToolOutcome(result, executed=True)

        self.state.failed_verifications += 1
        remaining = access_policy.MAX_VERIFICATION_ATTEMPTS - self.state.failed_verifications
        if remaining <= 0:
            self.state.locked_out = True
        return ToolOutcome({"verified": False, "attempts_remaining": max(remaining, 0),
                            "locked": self.state.locked_out}, executed=True)

    def _get_pay_statement(self, args: dict, _: str) -> ToolOutcome:
        statement = self.wfm.get_pay_statement(args["employee_id"], args["period"].strip() or "latest")
        statement["available_statements"] = self.wfm.list_pay_statements(args["employee_id"])
        return ToolOutcome(statement, executed=True)

    def _get_timecards(self, args: dict, _: str) -> ToolOutcome:
        return ToolOutcome(self.wfm.get_timecards(args["employee_id"], args["start_date"], args["end_date"]),
                           executed=True)

    def _get_roster(self, args: dict, _: str) -> ToolOutcome:
        return ToolOutcome(self.wfm.get_roster(args["employee_id"], args["start_date"], args["end_date"]),
                           executed=True)

    def _get_leave_balance(self, args: dict, _: str) -> ToolOutcome:
        balances = self.wfm.get_leave_balances(args["employee_id"])
        balances["requests"] = self.wfm.get_leave_requests(args["employee_id"])["requests"]
        return ToolOutcome(balances, executed=True)

    def _submit_leave_request(self, args: dict, latest_user_text: str) -> ToolOutcome:
        gate = confirmation.check_write(args, self.state.pending_leave, self.state.user_turn, latest_user_text)
        if gate.action == "allow":
            created = self.wfm.create_leave_request(args["employee_id"], args["leave_type"], args["start_date"],
                                                    args["end_date"], dry_run=False)
            self.state.pending_leave = None
            self.state.submitted_leave_requests.append(created["request"]["request_id"])
            return ToolOutcome({"status": "submitted", **created}, decisions=[gate], executed=True)

        # Phase 1: validate with a dry run, remember exactly what the user will be asked to confirm.
        preview = self.wfm.create_leave_request(args["employee_id"], args["leave_type"], args["start_date"],
                                                args["end_date"], dry_run=True)
        self.state.pending_leave = {"key": confirmation.leave_request_key(args), "preview": preview,
                                    "user_turn": self.state.user_turn}
        return ToolOutcome({
            "status": "confirmation_required",
            "submitted": False,
            "preview": preview["would_create"],
            "available_hours_after": preview["available_hours_after"],
            "instruction": "Nothing has been submitted yet. Show the user these exact details (leave type, dates, "
                           "hours) and ask them to confirm. Call submit_leave_request again with identical "
                           "arguments only after the user explicitly says yes.",
        }, decisions=[gate], executed=True)

    def _create_ticket(self, args: dict, _: str) -> ToolOutcome:
        ticket = self._open_ticket(
            subject=f"[Helpdesk bot] {args['category']}: {args['summary']}",
            details=args["details"], priority=args["priority"], ticket_type=TICKET_TYPE[args["category"]],
            tags=["helpdesk-bot", args["category"]])
        return ToolOutcome({**ticket, "message": f"Ticket #{ticket['ticket_id']} created. The payroll team will "
                                                 f"follow up {SLA[args['priority']]}."}, executed=True)

    def _escalate_to_human(self, args: dict, _: str) -> ToolOutcome:
        if self.state.escalation_ticket_id is not None:
            return ToolOutcome({"already_escalated": True, "ticket_id": self.state.escalation_ticket_id,
                                "message": "This conversation was already handed to a payroll officer."})
        ticket = self.escalate(args["reason"], args["summary"], args["details"], args["urgency"])
        return ToolOutcome({**ticket, "handoff": f"Handed to a payroll officer, who will contact the employee "
                                                 f"{SLA[args['urgency']]}. Tell the user the ticket number."},
                           executed=True)

    # --- shared ticket helpers (the escalation backstop uses escalate() too) ---------------------
    def escalate(self, reason: str, summary: str, details: str, urgency: str) -> dict:
        ticket = self._open_ticket(
            subject=f"[Helpdesk bot] Escalation ({reason}): {summary}", details=details, priority=urgency,
            ticket_type="incident" if reason == "payroll_error_suspected" else "question",
            tags=["helpdesk-bot", "escalation", reason])
        self.state.escalation_ticket_id = ticket["ticket_id"]
        self.state.escalation_reason = reason
        return ticket

    def _open_ticket(self, subject: str, details: str, priority: str, ticket_type: str, tags: list[str]) -> dict:
        employee = self.state.verified_employee_id or "UNVERIFIED"
        body = (f"Employee: {employee}\nConversation: {self.state.conversation_id}\n\n"
                f"{self.redactor.text(details)}")  # data minimisation: no DOB/postcode/names in tickets
        ticket = self.tickets.create_ticket(subject=self.redactor.text(subject), body=body, priority=priority,
                                            ticket_type=ticket_type, tags=tags,
                                            external_id=self.state.verified_employee_id)
        self.state.ticket_ids.append(ticket["ticket_id"])
        return ticket
