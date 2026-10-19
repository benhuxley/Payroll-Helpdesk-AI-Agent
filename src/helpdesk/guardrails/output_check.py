"""Layer 4: check the agent's reply before the user sees it.

If a rule fails, the reply is replaced with a safe message, and the model is told on the next turn
what happened (so the conversation stays consistent).
Rules:
  - sensitive_identifier: TFN-like or bank-like numbers, or masked TFN/bank strings
  - dob_echo: anything that looks like a date of birth (years 1930-2010)
  - data_before_verification: dollar amounts before the user is verified (except published allowance rates)
  - other_employee_id / other_employee_name: anyone other than the verified employee (or their own manager)
"""

import re

from helpdesk.guardrails.decisions import GuardrailDecision

LAYER = "output_check"

SAFE_REPLY = ("Sorry, I can't share that information here. I can help with your own pay, timecards, roster "
              "and leave once you're verified, or I can pass your question to the payroll team.")

# Amounts that come from the published pay rules, so they're fine to mention before verification.
PUBLIC_AMOUNTS = {"18.40"}

TFN_LIKE = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b")
BSB_LIKE = re.compile(r"\b\d{3}-\d{3}\b")
MASKED = re.compile(r"\*{3}[ -]?\*{3}|\*{4}\d{4}")
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{2})?)")
EMPLOYEE_ID = re.compile(r"\bE\d{4}\b")
_YEAR = r"(19[3-9]\d|200\d|2010)"
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
DOB_LIKE = re.compile(
    rf"\b{_YEAR}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}/\d{{1,2}}/{_YEAR}\b"
    rf"|\b\d{{1,2}}(st|nd|rd|th)? {_MONTH},? {_YEAR}\b|\b{_MONTH} \d{{1,2}}(st|nd|rd|th)?,? {_YEAR}\b",
    re.IGNORECASE,
)


def _name_pattern(name: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(name)}\b")


def find_violations(text: str, verified_employee_id: str | None, directory: list[dict]) -> list[tuple[str, str]]:
    violations = []
    if TFN_LIKE.search(text) or BSB_LIKE.search(text) or MASKED.search(text):
        violations.append(("sensitive_identifier", "TFN/bank-like number in reply"))
    if DOB_LIKE.search(text):
        violations.append(("dob_echo", "date-of-birth-like date in reply"))

    if not verified_employee_id:
        amounts = {m.replace(",", "") for m in MONEY.findall(text)} - PUBLIC_AMOUNTS
        if amounts:
            violations.append(("data_before_verification", f"dollar amounts before verification: {sorted(amounts)}"))
        return violations

    others_ids = {m for m in EMPLOYEE_ID.findall(text)} - {verified_employee_id}
    if others_ids:
        violations.append(("other_employee_id", f"mentions {sorted(others_ids)}"))

    me = next((e for e in directory if e["employee_id"] == verified_employee_id), None)
    allowed = {verified_employee_id, me["manager_id"] if me else None}
    for person in directory:
        if person["employee_id"] in allowed:
            continue
        for name in (f"{person['first_name']} {person['last_name']}", person["first_name"]):
            if _name_pattern(name).search(text):
                violations.append(("other_employee_name", f"mentions another employee ({person['employee_id']})"))
                break
    return violations


def check_reply(text: str, verified_employee_id: str | None, directory: list[dict]) \
        -> tuple[str, list[GuardrailDecision]]:
    """Return (text to show the user, decisions)."""
    violations = find_violations(text, verified_employee_id, directory)
    if not violations:
        return text, [GuardrailDecision(LAYER, "passed", "allow")]
    decisions = [GuardrailDecision(LAYER, rule, "replace", detail) for rule, detail in violations]
    return SAFE_REPLY, decisions
