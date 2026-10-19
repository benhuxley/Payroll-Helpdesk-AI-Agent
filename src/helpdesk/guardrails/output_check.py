"""Layer 4: check the agent's reply before the user sees it.

If a rule fails, the reply is replaced with a safe message, and the model is told on the next turn
what happened (so the conversation stays consistent).
Rules:
  - sensitive_identifier: TFN-like or bank-like numbers, or masked TFN/bank strings
  - dob_echo: anything that looks like a date of birth (years 1930-2010)
  - data_before_verification: dollar amounts before the user is verified (except published allowance rates)
  - other_employee_id / other_employee_name: anyone other than the verified employee (or their own manager).
    Exception: a name or ID the user typed themselves may be repeated in a reply that contains no dollar
    amounts, e.g. "I can't look up E1005's leave". The risk is data about another person, not their name.
    (Found by the Haiku eval run: blocking those refusals replaced good answers with a generic one.)
"""

import re

from helpdesk.guardrails.decisions import GuardrailDecision

LAYER = "output_check"

SAFE_REPLY_UNVERIFIED = ("Sorry, I can't share that information here. I can help with your own pay, timecards, "
                         "roster and leave once you're verified, or I can pass your question to the payroll team.")
SAFE_REPLY_VERIFIED = ("Sorry, I can't share that information here. I can only help with your own pay, timecards, "
                       "roster and leave, or I can pass your question to the payroll team.")
SAFE_REPLY = SAFE_REPLY_UNVERIFIED  # kept for callers that don't know the state

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


def _mentions(token: str, text: str, ignore_case: bool = False) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE if ignore_case else 0) is not None


def find_violations(text: str, verified_employee_id: str | None, directory: list[dict],
                    user_text: str = "") -> list[tuple[str, str]]:
    violations = []
    if TFN_LIKE.search(text) or BSB_LIKE.search(text) or MASKED.search(text):
        violations.append(("sensitive_identifier", "TFN/bank-like number in reply"))
    if DOB_LIKE.search(text):
        violations.append(("dob_echo", "date-of-birth-like date in reply"))

    has_amounts = bool(MONEY.search(text))
    if not verified_employee_id:
        amounts = {m.replace(",", "") for m in MONEY.findall(text)} - PUBLIC_AMOUNTS
        if amounts:
            violations.append(("data_before_verification", f"dollar amounts before verification: {sorted(amounts)}"))
        return violations

    def user_introduced(token: str) -> bool:
        return not has_amounts and _mentions(token, user_text, ignore_case=True)

    others_ids = {m for m in EMPLOYEE_ID.findall(text)} - {verified_employee_id}
    others_ids = {i for i in others_ids if not user_introduced(i)}
    if others_ids:
        violations.append(("other_employee_id", f"mentions {sorted(others_ids)}"))

    me = next((e for e in directory if e["employee_id"] == verified_employee_id), None)
    allowed = {verified_employee_id, me["manager_id"] if me else None}
    for person in directory:
        if person["employee_id"] in allowed:
            continue
        for name in (f"{person['first_name']} {person['last_name']}", person["first_name"]):
            if _mentions(name, text) and not user_introduced(name):
                violations.append(("other_employee_name", f"mentions another employee ({person['employee_id']})"))
                break
    return violations


def check_reply(text: str, verified_employee_id: str | None, directory: list[dict], user_text: str = "") \
        -> tuple[str, list[GuardrailDecision]]:
    """Return (text to show the user, decisions). user_text: everything the user has typed so far."""
    violations = find_violations(text, verified_employee_id, directory, user_text)
    if not violations:
        return text, [GuardrailDecision(LAYER, "passed", "allow")]
    decisions = [GuardrailDecision(LAYER, rule, "replace", detail) for rule, detail in violations]
    return (SAFE_REPLY_VERIFIED if verified_employee_id else SAFE_REPLY_UNVERIFIED), decisions
