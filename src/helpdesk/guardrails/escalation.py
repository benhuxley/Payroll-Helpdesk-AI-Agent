"""Layer 5: escalation rules.

The model decides most escalations itself (payroll error found, low confidence) by calling escalate_to_human.
Some rules are deterministic and *mandatory*. If one fires and the model's turn ends without a handoff,
the harness creates the escalation itself (the "backstop").
"""

from helpdesk.agent.state import ConversationState
from helpdesk.guardrails.decisions import GuardrailDecision

LAYER = "escalation"

REASONS = [
    "payroll_error_suspected",  # the data shows the employee was paid incorrectly
    "user_requested_human",
    "user_distressed",  # very upset, or financial hardship
    "low_confidence",  # the data can't explain it, or it's contradictory
    "verification_failed",  # locked out after 3 failed attempts
    "out_of_policy_request",
    "other",
]

# input_screen flag -> mandatory escalation reason
MANDATORY_FROM_FLAGS = {
    "requests_human": "user_requested_human",
    "strong_frustration": "user_distressed",
    "financial_distress": "user_distressed",
}


def mandatory_reason(input_flags: list[str], state: ConversationState) -> str | None:
    """The reason this turn *must* end with a handoff, or None."""
    for flag in input_flags:
        if flag in MANDATORY_FROM_FLAGS:
            return MANDATORY_FROM_FLAGS[flag]
    if state.locked_out:
        return "verification_failed"
    return None


def backstop(required_reason: str | None, state: ConversationState) -> GuardrailDecision | None:
    """If an escalation was required but hasn't happened, return a decision for the harness to act on."""
    if required_reason is None or state.escalation_ticket_id is not None:
        return None
    return GuardrailDecision(LAYER, f"backstop_{required_reason}", "escalate",
                             "Mandatory escalation rule fired but the model did not hand off.")
