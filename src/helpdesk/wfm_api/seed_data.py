"""Synthetic seed data for the fictional employer "Kestrel Bay Health".

Every person, number and address here is made up. Nothing comes from a real client.

The data is built so that each "tricky case" has an exact, known answer (ground truth for the evals):

    E1001 Priya Nair     - missed clock-out on Tue 6 Oct -> 7.5h unpaid -> $330.00 short. Routine fix: ticket.
    E1002 Daniel Okafor  - annual leave request for 3-6 Nov is still PENDING manager approval.
    E1003 Mei Lin Zhao   - Sunday 4 Oct shift was manually entered and coded ORD instead of SUN,
                           so it was paid at 100% instead of 175% -> $180.00 underpaid. Payroll error: escalate.
    E1004 Jack Thompson  - 2h overtime on Thu 8 Oct was approved AFTER the timecard cutoff, so it is
                           paid in the next pay run (28 Oct). Not an error: explain, don't escalate.
    E1005 Aroha Ngata    - worked the King's Birthday public holiday (Mon 5 Oct) at 250%. Pay is correct.
    E1007 Liam O'Brien   - only 12h annual leave available, not enough for a week off.
    E1008 Hannah Kowalski- 3h overtime on Wed 30 Sep: 2h at 150% + 1h at 200% + meal allowance. Correct.
    E1009 Raj Patel      - unexplained manual adjustment of -$212.40. The data can't explain it: escalate.

The bugs live in the *timecard data*, not in the pay engine. The engine pays exactly what the timecard says,
which is how these problems usually happen in real payroll.
"""

from datetime import date

# --- Pay periods (fortnightly, Monday to Sunday) -------------------------------------------------------
PAY_PERIODS = [
    # (period_start, period_end, pay_date, timecard approval cutoff)
    (date(2026, 9, 14), date(2026, 9, 27), date(2026, 9, 30), "2026-09-28T10:00"),
    (date(2026, 9, 28), date(2026, 10, 11), date(2026, 10, 14), "2026-10-12T10:00"),
    (date(2026, 10, 12), date(2026, 10, 25), date(2026, 10, 28), "2026-10-26T10:00"),  # in progress
]
PAID_PERIOD_ENDS = [date(2026, 9, 27), date(2026, 10, 11)]  # periods that already have a pay statement

PUBLIC_HOLIDAYS = {date(2026, 10, 5): "King's Birthday (QLD)"}

ROSTER_START = date(2026, 9, 14)
ROSTER_END = date(2026, 11, 29)
TIMECARDS_UNTIL = date(2026, 10, 18)  # the day before AS_OF_DATE

# --- Employees ----------------------------------------------------------------------------------------
# pattern: which weekdays they work (0 = Monday). "fortnight_pattern" overrides per week of the fortnight.
EMPLOYEES = [
    {
        "employee_id": "E1001", "first_name": "Priya", "last_name": "Nair",
        "date_of_birth": "1991-03-14", "postcode": "4101", "position": "Registered Nurse",
        "department": "Ward 4B", "employment_type": "full_time", "base_rate": 44.00,
        "manager_id": "E1006", "shift": ("07:00", "15:00"), "pattern": [0, 1, 2, 3, 4],
    },
    {
        "employee_id": "E1002", "first_name": "Daniel", "last_name": "Okafor",
        "date_of_birth": "1987-11-02", "postcode": "4120", "position": "Enrolled Nurse",
        "department": "Ward 4B", "employment_type": "part_time", "base_rate": 36.00,
        "manager_id": "E1006", "shift": ("07:00", "15:00"), "pattern": [1, 2, 3, 4],
    },
    {
        "employee_id": "E1003", "first_name": "Mei Lin", "last_name": "Zhao",
        "date_of_birth": "1998-06-25", "postcode": "4006", "position": "Assistant in Nursing",
        "department": "Ward 4B", "employment_type": "part_time", "base_rate": 32.00,
        "manager_id": "E1006", "shift": ("07:00", "15:00"),
        # week 1: Thu Fri Sat Sun, week 2: Wed Thu Fri Sat
        "fortnight_pattern": [[3, 4, 5, 6], [2, 3, 4, 5]],
    },
    {
        "employee_id": "E1004", "first_name": "Jack", "last_name": "Thompson",
        "date_of_birth": "1979-01-30", "postcode": "4170", "position": "Wardsperson",
        "department": "Patient Transport", "employment_type": "full_time", "base_rate": 30.00,
        "manager_id": "E1009", "shift": ("07:00", "15:00"), "pattern": [0, 1, 2, 3, 4],
    },
    {
        "employee_id": "E1005", "first_name": "Aroha", "last_name": "Ngata",
        "date_of_birth": "1993-09-08", "postcode": "4059", "position": "Registered Nurse",
        "department": "Ward 4B", "employment_type": "full_time", "base_rate": 44.00,
        "manager_id": "E1006", "shift": ("07:00", "15:00"), "pattern": [0, 1, 2, 3, 4],
        "works_public_holidays": True,
    },
    {
        "employee_id": "E1006", "first_name": "Sofia", "last_name": "Rossi",
        "date_of_birth": "1982-04-17", "postcode": "4064", "position": "Nurse Unit Manager",
        "department": "Ward 4B", "employment_type": "full_time", "base_rate": 55.00,
        "manager_id": "E1009", "shift": ("08:00", "16:00"), "pattern": [0, 1, 2, 3, 4],
    },
    {
        "employee_id": "E1007", "first_name": "Liam", "last_name": "O'Brien",
        "date_of_birth": "2001-12-05", "postcode": "4030", "position": "Kitchen Hand",
        "department": "Food Services", "employment_type": "part_time", "base_rate": 28.00,
        "manager_id": "E1009", "shift": ("10:00", "18:00"), "pattern": [0, 2, 4],
    },
    {
        "employee_id": "E1008", "first_name": "Hannah", "last_name": "Kowalski",
        "date_of_birth": "1990-07-21", "postcode": "4151", "position": "Administration Officer",
        "department": "Administration", "employment_type": "full_time", "base_rate": 35.00,
        "manager_id": "E1009", "shift": ("08:30", "16:30"), "pattern": [0, 1, 2, 3, 4],
    },
    {
        "employee_id": "E1009", "first_name": "Raj", "last_name": "Patel",
        "date_of_birth": "1976-02-11", "postcode": "4152", "position": "Operations Manager",
        "department": "Operations", "employment_type": "full_time", "base_rate": 52.00,
        "manager_id": None, "shift": ("08:00", "16:00"), "pattern": [0, 1, 2, 3, 4],
    },
]

LOCATIONS = {
    "Ward 4B": "Ward 4B, Kestrel Bay Hospital",
    "Patient Transport": "Patient Transport, Kestrel Bay Hospital",
    "Food Services": "Main Kitchen, Kestrel Bay Hospital",
    "Administration": "Admin Office, Level 2",
    "Operations": "Operations Office, Level 2",
}

# --- Timecard overrides: the deliberate "tricky cases" ---------------------------------------------
# Keyed by (employee_id, ISO date). Fields here replace the generated defaults for that day.
TIMECARD_OVERRIDES = {
    # E1001: forgot to clock out. The shift is an unresolved exception, so it paid 0 hours.
    ("E1001", "2026-10-06"): {
        "punch_out": None, "paid_hours": 0.0,
        "exception": "MISSED_PUNCH: no clock-out recorded. Unresolved - awaiting manager correction. "
                     "Hours on an unresolved exception are not paid until corrected.",
    },
    # E1003: Sunday shift keyed in manually while the clock was offline, with the wrong pay code.
    ("E1003", "2026-10-04"): {
        "pay_code": "ORD",
        "manual_edit_note": "Punches entered manually by timekeeper on 2026-10-06 (time clock offline).",
    },
    # E1004: 2h overtime, approved the day after the cutoff -> paid next pay run.
    ("E1004", "2026-10-08"): {
        "punch_out": "17:02", "overtime_hours": 2.0, "overtime_approved_at": "2026-10-13T09:15",
    },
    # E1008: 3h overtime approved on time -> 2h @150%, 1h @200%, plus meal allowance (OT > 2h).
    ("E1008", "2026-09-30"): {
        "punch_out": "19:31", "overtime_hours": 3.0, "overtime_approved_at": "2026-10-01T09:40",
    },
}

# Days that are leave rather than worked shifts (approved leave already taken).
LEAVE_TAKEN = {
    ("E1008", "2026-09-21"): "PERS",
}

# One-off manual adjustments on a pay statement: (employee_id, period_end) -> lines
MANUAL_ADJUSTMENTS = {
    ("E1009", "2026-10-11"): [
        {"code": "ADJ", "description": "Adjustment - manual (ref ADJ-7731)", "amount": -212.40},
    ],
}

# --- Leave ---------------------------------------------------------------------------------------
LEAVE_BALANCES = {
    # employee_id: {leave_type: hours}
    "E1001": {"annual": 96.0, "personal": 52.5, "long_service": 0.0},
    "E1002": {"annual": 82.5, "personal": 45.0, "long_service": 0.0},
    "E1003": {"annual": 40.0, "personal": 22.5, "long_service": 0.0},
    "E1004": {"annual": 150.0, "personal": 75.0, "long_service": 260.0},
    "E1005": {"annual": 120.0, "personal": 60.0, "long_service": 0.0},
    "E1006": {"annual": 110.0, "personal": 70.0, "long_service": 120.0},
    "E1007": {"annual": 12.0, "personal": 15.0, "long_service": 0.0},
    "E1008": {"annual": 64.5, "personal": 38.0, "long_service": 0.0},
    "E1009": {"annual": 175.0, "personal": 90.0, "long_service": 310.0},
}

LEAVE_REQUESTS = [
    {"request_id": "LR-1987", "employee_id": "E1002", "leave_type": "annual",
     "start_date": "2026-08-18", "end_date": "2026-08-21", "hours": 30.0, "status": "approved",
     "submitted_at": "2026-07-29T10:05", "decided_at": "2026-08-03T16:40", "approver_id": "E1006"},
    {"request_id": "LR-2003", "employee_id": "E1008", "leave_type": "personal",
     "start_date": "2026-09-21", "end_date": "2026-09-21", "hours": 7.5, "status": "approved",
     "submitted_at": "2026-09-21T07:12", "decided_at": "2026-09-21T09:30", "approver_id": "E1009"},
    {"request_id": "LR-2041", "employee_id": "E1002", "leave_type": "annual",
     "start_date": "2026-11-03", "end_date": "2026-11-06", "hours": 30.0, "status": "pending",
     "submitted_at": "2026-10-12T14:22", "decided_at": None, "approver_id": "E1006"},
    {"request_id": "LR-2050", "employee_id": "E1004", "leave_type": "annual",
     "start_date": "2026-12-21", "end_date": "2026-12-24", "hours": 30.0, "status": "approved",
     "submitted_at": "2026-09-02T11:00", "decided_at": "2026-09-04T08:15", "approver_id": "E1009"},
]
