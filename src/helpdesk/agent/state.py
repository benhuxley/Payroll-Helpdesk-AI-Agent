from dataclasses import dataclass, field


@dataclass
class ConversationState:
    """Facts the *harness* knows for certain. The model never sets these directly.

    For example, verified_employee_id is only set when the WFM API says the identity check passed,
    not when the model says "thanks, you're verified".
    """

    conversation_id: str
    verified_employee_id: str | None = None
    verified_first_name: str | None = None
    failed_verifications: int = 0
    locked_out: bool = False
    user_turn: int = 0
    pending_leave: dict | None = None  # {"key": (...), "preview": {...}, "user_turn": n}
    submitted_leave_requests: list[str] = field(default_factory=list)
    ticket_ids: list[int] = field(default_factory=list)
    escalation_ticket_id: int | None = None
    escalation_reason: str | None = None
