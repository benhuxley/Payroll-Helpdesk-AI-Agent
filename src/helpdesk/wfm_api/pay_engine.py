"""A deliberately small pay engine for the fictional Kestrel Bay Health Enterprise Agreement.

It turns approved timecards into pay statement lines. It pays exactly what the timecard says,
so a wrong pay code on a timecard becomes a wrong pay line (that's the realistic part).

Rules (also summarised for the agent in agent/prompts/system_v1.md):
  - Ordinary hours: 100% of base rate (Mon-Fri).
  - Saturday: 150%. Sunday: 175%. Public holiday worked: 250%.
  - Public holiday not worked (rostered day off because of the holiday): 100% for a normal shift (7.5h).
  - Overtime (time beyond the rostered shift, approved by the manager): first 2h on a day at 150%,
    after that 200%. A meal allowance of $18.40 is paid when overtime on a day is more than 2 hours.
  - Timecards (including overtime) approved after the cutoff (Monday 10:00 after the period ends)
    are paid in the next pay run.
  - Hours on an unresolved timecard exception (e.g. a missed punch) are not paid until corrected.
  - Tax here is a synthetic flat 22% (rounded to whole dollars). It is NOT the real ATO withholding table.
  - Super: 12% of ordinary time earnings (not overtime or allowances).
"""

from datetime import date

from helpdesk.wfm_api.seed_data import PUBLIC_HOLIDAYS

PAY_CODES = {
    # code: (description, multiplier of base rate)
    "ORD": ("Ordinary hours", 1.0),
    "SAT": ("Saturday penalty 150%", 1.5),
    "SUN": ("Sunday penalty 175%", 1.75),
    "PH": ("Public holiday worked 250%", 2.5),
    "PHNW": ("Public holiday not worked", 1.0),
    "AL": ("Annual leave", 1.0),
    "PERS": ("Personal/carer's leave", 1.0),
    "OT150": ("Overtime 150% (first 2 hours)", 1.5),
    "OT200": ("Overtime 200% (after 2 hours)", 2.0),
}
LINE_ORDER = ["ORD", "SAT", "SUN", "PH", "PHNW", "AL", "PERS", "OT150", "OT200"]

MEAL_ALLOWANCE = 18.40
OVERTIME_FIRST_TIER_HOURS = 2.0
TAX_RATE = 0.22  # synthetic
SUPER_RATE = 0.12
ORDINARY_TIME_CODES = {"ORD", "SAT", "SUN", "PH", "PHNW", "AL", "PERS"}


def expected_pay_code(day: date) -> str:
    """The pay code a worked shift on this day *should* have."""
    if day in PUBLIC_HOLIDAYS:
        return "PH"
    if day.weekday() == 5:
        return "SAT"
    if day.weekday() == 6:
        return "SUN"
    return "ORD"


def split_overtime(overtime_hours: float) -> tuple[float, float]:
    """Return (hours at 150%, hours at 200%)."""
    first = min(overtime_hours, OVERTIME_FIRST_TIER_HOURS)
    return first, overtime_hours - first


def build_pay_statement(base_rate: float, timecards: list[dict], cutoff: str,
                        adjustments: list[dict] | None = None) -> dict:
    """Build pay lines and totals for one pay period.

    timecards: rows for the period (dicts with pay_code, paid_hours, overtime_hours, overtime_approved_at).
    cutoff: ISO datetime string. Overtime approved after it is left for the next pay run.
    """
    hours_by_code = {code: 0.0 for code in LINE_ORDER}
    meal_allowances = 0

    for tc in timecards:
        hours_by_code[tc["pay_code"]] += tc["paid_hours"]

        overtime = tc.get("overtime_hours") or 0.0
        approved_at = tc.get("overtime_approved_at")
        if overtime and approved_at and approved_at <= cutoff:
            at_150, at_200 = split_overtime(overtime)
            hours_by_code["OT150"] += at_150
            hours_by_code["OT200"] += at_200
            if overtime > OVERTIME_FIRST_TIER_HOURS:
                meal_allowances += 1

    lines = []
    for code in LINE_ORDER:
        hours = hours_by_code[code]
        if hours == 0:
            continue
        description, multiplier = PAY_CODES[code]
        rate = round(base_rate * multiplier, 2)
        lines.append({"code": code, "description": description, "hours": hours, "rate": rate,
                      "amount": round(hours * rate, 2)})

    if meal_allowances:
        lines.append({"code": "MEAL", "description": "Meal allowance (overtime over 2 hours)",
                      "hours": None, "rate": MEAL_ALLOWANCE, "quantity": meal_allowances,
                      "amount": round(meal_allowances * MEAL_ALLOWANCE, 2)})

    for adj in adjustments or []:
        lines.append({"code": adj["code"], "description": adj["description"], "hours": None,
                      "rate": None, "amount": adj["amount"]})

    gross = round(sum(line["amount"] for line in lines), 2)
    ordinary_earnings = sum(line["amount"] for line in lines if line["code"] in ORDINARY_TIME_CODES)
    tax = float(round(gross * TAX_RATE))
    return {
        "lines": lines,
        "gross": gross,
        "tax_withheld": tax,
        "net": round(gross - tax, 2),
        "super_contribution": round(ordinary_earnings * SUPER_RATE, 2),
    }
