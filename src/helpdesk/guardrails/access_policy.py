"""Layer 2: decide whether a tool call is allowed, *before* it touches the WFM system.

This is enforced in code, not left to the prompt. The model can be talked into anything; this function can't.
  - No personal data tools until verify_identity has succeeded.
  - Data tools only for the verified employee's own employee_id.
  - One identity per conversation, and a lockout after 3 failed verification attempts.
"""

from helpdesk.agent.state import ConversationState
from helpdesk.guardrails.decisions import GuardrailDecision

LAYER = "access_policy"
MAX_VERIFICATION_ATTEMPTS = 3

DATA_TOOLS = {"get_pay_statement", "get_timecards", "get_roster", "get_leave_balance", "submit_leave_request"}
NEEDS_VERIFIED_USER = DATA_TOOLS | {"create_ticket"}
ALWAYS_ALLOWED = {"escalate_to_human"}  # anyone can be handed to a person
KNOWN_TOOLS = NEEDS_VERIFIED_USER | ALWAYS_ALLOWED | {"verify_identity"}


def _block(rule: str, detail: str) -> GuardrailDecision:
    return GuardrailDecision(layer=LAYER, rule=rule, action="block", detail=detail)


def check_tool_call(tool_name: str, tool_input: dict, state: ConversationState) -> GuardrailDecision:
    if tool_name not in KNOWN_TOOLS:
        return _block("unknown_tool", f"Tool '{tool_name}' does not exist.")

    if tool_name == "verify_identity":
        if state.locked_out:
            return _block("verification_locked",
                          "Verification is locked after 3 failed attempts. Do not ask for details again. "
                          "Hand off with escalate_to_human (reason: verification_failed).")
        claimed = str(tool_input.get("employee_id", "")).strip().upper()
        if state.verified_employee_id and claimed != state.verified_employee_id:
            return _block("identity_switch",
                          f"This conversation is already verified as {state.verified_employee_id}. "
                          "Only one identity per conversation. Other employees must contact the helpdesk themselves.")
        return GuardrailDecision(layer=LAYER, rule="verification_attempt", action="allow")

    if tool_name in NEEDS_VERIFIED_USER and not state.verified_employee_id:
        return _block("verification_required",
                      "Identity not verified. Ask the user for their employee ID, date of birth and home "
                      "postcode, then call verify_identity. Do not share any personal information before that.")

    if tool_name in DATA_TOOLS:
        requested = str(tool_input.get("employee_id", "")).strip().upper()
        if requested != state.verified_employee_id:
            return _block("not_own_record",
                          f"Access denied: only the verified employee's own records ({state.verified_employee_id}) "
                          "can be accessed. Do not reveal anything about other employees.")

    return GuardrailDecision(layer=LAYER, rule="allowed", action="allow")
