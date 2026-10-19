from dataclasses import asdict, dataclass


@dataclass
class GuardrailDecision:
    """One decision made by one guardrail layer. Every decision is written to the trace."""

    layer: str  # input_screen | access_policy | confirmation_gate | output_check | escalation
    rule: str  # short machine-readable name, e.g. "verification_required"
    action: str  # allow | block | flag | hold | replace | escalate
    detail: str = ""
    note_for_model: str | None = None  # optional operator note passed to the model (system role)

    def to_dict(self) -> dict:
        return asdict(self)
