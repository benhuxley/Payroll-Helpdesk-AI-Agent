"""Layered guardrails. Each module is one layer and can be unit-tested on its own.

Order in a conversation turn:
  1. input_screen      - deterministic flags on the user's message -> operator notes to the model
  2. access_policy     - every tool call: verification required, own records only, lockout
  3. confirmation      - writes (leave requests) need a preview + an explicit "yes" from the user
  4. output_check      - the reply is checked before the user sees it
  5. escalation        - if a rule says "escalate" and the model didn't, the harness does it
  6. redaction         - personal data is removed from traces/logs at write time
"""
