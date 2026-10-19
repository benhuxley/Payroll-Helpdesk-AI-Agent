"""Layer 3: writes need an explicit confirmation from the user, checked in code.

Flow for submit_leave_request (two-phase commit):
  1. First call  -> the harness runs a *dry run* against the WFM API, stores the exact details as "pending",
                    and tells the model: nothing was submitted, show these details and ask the user to confirm.
  2. User replies -> if the next user message is an explicit "yes" (is_explicit_confirmation) AND the model
                    calls again with the *same* details, the request is really submitted.
Anything else (different dates, "yes but...", no new user message) goes back to step 1.
We never trust the model saying "the user confirmed". We check the user's actual words.
"""

import re

from helpdesk.guardrails.decisions import GuardrailDecision

LAYER = "confirmation_gate"

_AFFIRMATIVE = re.compile(
    r"^(yes|yep|yeah|yup|y|sure|ok|okay|correct|confirm(ed)?|i confirm|that'?s (right|correct)|go ahead|"
    r"please (do|submit|go ahead|lodge)|submit( it)?|lodge( it)?|do it|sounds good|perfect|all good|looks good)\b",
)
_NEGATIVE = re.compile(
    r"\b(no|nope|not|don'?t|dont|wait|hold on|hang on|cancel|stop|change|instead|actually|but|wrong|rather)\b",
)


def is_explicit_confirmation(text: str) -> bool:
    normalised = re.sub(r"[^\w\s']", " ", text.lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    if not normalised or _NEGATIVE.search(normalised):
        return False
    return bool(_AFFIRMATIVE.match(normalised))


def leave_request_key(tool_input: dict) -> tuple:
    """The exact details the user must confirm. Any difference means a new confirmation."""
    return (
        str(tool_input.get("employee_id", "")).strip().upper(),
        str(tool_input.get("leave_type", "")).strip().lower(),
        str(tool_input.get("start_date", "")).strip(),
        str(tool_input.get("end_date", "")).strip(),
    )


def check_write(tool_input: dict, pending: dict | None, user_turn: int, latest_user_text: str) -> GuardrailDecision:
    """Decide whether this submit call is the confirmed second phase ('allow') or needs a preview ('hold')."""
    key = leave_request_key(tool_input)
    if pending is None:
        return GuardrailDecision(LAYER, "preview_required", "hold", "No confirmed preview yet.")
    if pending["key"] != key:
        return GuardrailDecision(LAYER, "details_changed", "hold",
                                 "Details differ from the preview the user saw, so a new confirmation is needed.")
    if user_turn <= pending["user_turn"]:
        return GuardrailDecision(LAYER, "awaiting_user_reply", "hold",
                                 "The user hasn't replied to the preview yet.")
    if not is_explicit_confirmation(latest_user_text):
        return GuardrailDecision(LAYER, "no_explicit_confirmation", "hold",
                                 "The user's reply was not an explicit, unconditional yes.")
    return GuardrailDecision(LAYER, "confirmed", "allow", "User explicitly confirmed the previewed details.")
