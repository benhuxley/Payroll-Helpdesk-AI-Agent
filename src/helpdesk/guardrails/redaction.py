"""Layer 6: remove personal data from anything we write to disk (traces, logs, ticket bodies).

Two techniques, used together:
  - key-based: structured fields we know are sensitive (date_of_birth, postcode, email...) are replaced outright
  - pattern-based: free text (user messages, model replies) is scanned for emails, phone numbers,
    TFN/bank-like numbers, dates of birth, postcodes, and names from the employee directory.
Names become a pseudonym like [NAME:E1001], so a trace is still debuggable without exposing the person.
Employee IDs, pay amounts and dates of work are kept on purpose: you need them to debug a pay question.
"""

import re

REDACT_KEYS = {"date_of_birth", "postcode", "email", "phone", "tfn", "tfn_masked", "bank", "bank_masked"}
NAME_KEYS = {"first_name", "last_name", "name", "employee_name", "approver_name", "manager_name"}

_YEAR = r"(?:19[3-9]\d|200\d|2010)"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?:\+?61\s?|\b0)4\d{2}[\s-]?\d{3}[\s-]?\d{3}\b"), "[PHONE]"),
    (re.compile(r"\(0\d\)\s?\d{4}\s?\d{4}"), "[PHONE]"),
    (re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"), "[TFN]"),
    (re.compile(r"\b\d{3}-\d{3}\b"), "[BSB]"),
    (re.compile(r"(?i)\b(acc(?:oun)?t|acct)(\s*(?:no\.?|number|#))?[:\s]*\d[\d\s-]{4,14}\d"), r"\1 [ACCOUNT]"),
    (re.compile(rf"\b{_YEAR}-\d{{2}}-\d{{2}}\b"), "[DOB]"),
    (re.compile(rf"\b\d{{1,2}}[/.-]\d{{1,2}}[/.-]{_YEAR}\b"), "[DOB]"),
    (re.compile(rf"(?i)\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH},?\s+{_YEAR}\b"), "[DOB]"),
    (re.compile(rf"(?i)\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+{_YEAR}\b"), "[DOB]"),
    # 4-digit numbers that aren't years, amounts, times or parts of IDs like E1001 / LR-3001
    (re.compile(r"(?<![-$.,:/\w])(?!19\d\d|20\d\d)\d{4}\b(?![.,:]\d)"), "[POSTCODE]"),
]


class Redactor:
    def __init__(self, directory: list[dict] | None = None):
        names = []
        for person in directory or []:
            pseudonym = f"[NAME:{person['employee_id']}]"
            names.append((f"{person['first_name']} {person['last_name']}", pseudonym))
            names.append((person["first_name"], pseudonym))
            names.append((person["last_name"], pseudonym))
        # Longest first, so "Mei Lin Zhao" is replaced before "Mei Lin".
        names.sort(key=lambda pair: len(pair[0]), reverse=True)
        self._names = [(re.compile(rf"\b{re.escape(n)}\b", re.IGNORECASE), p) for n, p in names]

    def text(self, value: str) -> str:
        for pattern, replacement in PATTERNS:
            value = pattern.sub(replacement, value)
        for pattern, pseudonym in self._names:
            value = pattern.sub(pseudonym, value)
        return value

    def value(self, obj):
        """Redact any JSON-like value (dicts, lists, strings)."""
        if isinstance(obj, dict):
            out = {}
            for key, val in obj.items():
                if key in REDACT_KEYS and val is not None:
                    out[key] = "[REDACTED]"
                elif key in NAME_KEYS and isinstance(val, str):
                    out[key] = self.text(val)
                else:
                    out[key] = self.value(val)
            return out
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        if isinstance(obj, str):
            return self.text(obj)
        return obj
