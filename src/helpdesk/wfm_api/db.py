"""SQLite schema and database builder for the mock WFM system.

`build_database(path)` creates a fresh database from seed_data.py: rosters are generated from each
employee's work pattern, timecards from the rosters (plus the deliberate overrides), and pay statements
by running the pay engine over the approved timecards.
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from helpdesk.wfm_api import seed_data as seed
from helpdesk.wfm_api.pay_engine import build_pay_statement, expected_pay_code

SCHEMA = """
CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, date_of_birth TEXT, postcode TEXT,
    email TEXT, phone TEXT, position TEXT, department TEXT, employment_type TEXT, base_rate REAL,
    manager_id TEXT, tfn_masked TEXT, bank_masked TEXT
);
CREATE TABLE rosters (
    id INTEGER PRIMARY KEY, employee_id TEXT, shift_date TEXT, start_time TEXT, end_time TEXT,
    break_minutes INTEGER, hours REAL, location TEXT
);
CREATE TABLE timecards (
    id INTEGER PRIMARY KEY, employee_id TEXT, work_date TEXT, rostered_start TEXT, rostered_end TEXT,
    punch_in TEXT, punch_out TEXT, break_minutes INTEGER, pay_code TEXT, paid_hours REAL,
    overtime_hours REAL, overtime_approved_at TEXT, exception TEXT, manual_edit_note TEXT,
    public_holiday TEXT, approved_at TEXT
);
CREATE TABLE pay_statements (
    statement_id TEXT PRIMARY KEY, employee_id TEXT, period_start TEXT, period_end TEXT, pay_date TEXT,
    base_rate REAL, gross REAL, tax_withheld REAL, net REAL, super_contribution REAL
);
CREATE TABLE pay_lines (
    id INTEGER PRIMARY KEY, statement_id TEXT, line_no INTEGER, code TEXT, description TEXT,
    hours REAL, rate REAL, quantity INTEGER, amount REAL
);
CREATE TABLE leave_balances (
    employee_id TEXT, leave_type TEXT, hours REAL, PRIMARY KEY (employee_id, leave_type)
);
CREATE TABLE leave_requests (
    request_id TEXT PRIMARY KEY, employee_id TEXT, leave_type TEXT, start_date TEXT, end_date TEXT,
    hours REAL, status TEXT, submitted_at TEXT, decided_at TEXT, approver_id TEXT, notes TEXT
);
CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, body TEXT, priority TEXT, type TEXT, status TEXT,
    tags TEXT, external_id TEXT, custom_fields TEXT, created_at TEXT
);
"""

SHIFT_BREAK_MINUTES = 30


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _shift_hours(start: str, end: str, break_minutes: int) -> float:
    fmt = "%H:%M"
    minutes = (datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).seconds / 60
    return round((minutes - break_minutes) / 60, 2)


def _shift_minus(time_str: str, minutes: int) -> str:
    t = datetime.strptime(time_str, "%H:%M") - timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def _works_on(employee: dict, day: date) -> bool:
    week_index = ((day - seed.ROSTER_START).days // 7) % 2
    pattern = employee["fortnight_pattern"][week_index] if "fortnight_pattern" in employee \
        else employee["pattern"]
    return day.weekday() in pattern


def _period_for(day: date):
    for period in seed.PAY_PERIODS:
        if period[0] <= day <= period[1]:
            return period
    return None


def _manager_approval_time(day: date) -> str | None:
    """Managers sign off timecards at 08:30 on cutoff day. The in-progress period isn't signed off yet."""
    period = _period_for(day)
    if period is None or period[1] not in seed.PAID_PERIOD_ENDS:
        return None
    return period[3].replace("10:00", "08:30")


def build_database(db_path: Path | str) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = connect(db_path)
    conn.executescript(SCHEMA)

    for i, emp in enumerate(seed.EMPLOYEES, start=1):
        email = f"{emp['first_name']}.{emp['last_name']}".lower().replace(" ", "").replace("'", "")
        conn.execute(
            "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (emp["employee_id"], emp["first_name"], emp["last_name"], emp["date_of_birth"], emp["postcode"],
             f"{email}@kestrelbay.example", f"0400 000 {100 + i}", emp["position"], emp["department"],
             emp["employment_type"], emp["base_rate"], emp["manager_id"],
             f"*** *** 1{i:02d}", f"BSB ***-**{i} Acct ****{5000 + i}"),
        )

        start, end = emp["shift"]
        shift_hours = _shift_hours(start, end, SHIFT_BREAK_MINUTES)
        for day in _daterange(seed.ROSTER_START, seed.ROSTER_END):
            if not _works_on(emp, day):
                continue
            iso = day.isoformat()
            holiday = seed.PUBLIC_HOLIDAYS.get(day)

            if holiday and not emp.get("works_public_holidays"):
                # Not rostered because of the holiday. Paid "public holiday not worked".
                if day <= seed.TIMECARDS_UNTIL:
                    conn.execute(
                        "INSERT INTO timecards (employee_id, work_date, pay_code, paid_hours, public_holiday,"
                        " approved_at, break_minutes) VALUES (?,?,?,?,?,?,0)",
                        (emp["employee_id"], iso, "PHNW", shift_hours, holiday, _manager_approval_time(day)),
                    )
                continue

            conn.execute(
                "INSERT INTO rosters (employee_id, shift_date, start_time, end_time, break_minutes, hours,"
                " location) VALUES (?,?,?,?,?,?,?)",
                (emp["employee_id"], iso, start, end, SHIFT_BREAK_MINUTES, shift_hours,
                 seed.LOCATIONS[emp["department"]]),
            )
            if day > seed.TIMECARDS_UNTIL:
                continue

            card = {
                "punch_in": _shift_minus(start, 2), "punch_out": _shift_minus(end, -3),
                "pay_code": expected_pay_code(day), "paid_hours": shift_hours,
                "overtime_hours": 0.0, "overtime_approved_at": None, "exception": None,
                "manual_edit_note": None,
            }
            leave_code = seed.LEAVE_TAKEN.get((emp["employee_id"], iso))
            if leave_code:
                card.update(punch_in=None, punch_out=None, pay_code=leave_code)
            card.update(seed.TIMECARD_OVERRIDES.get((emp["employee_id"], iso), {}))

            conn.execute(
                "INSERT INTO timecards (employee_id, work_date, rostered_start, rostered_end, punch_in,"
                " punch_out, break_minutes, pay_code, paid_hours, overtime_hours, overtime_approved_at,"
                " exception, manual_edit_note, public_holiday, approved_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (emp["employee_id"], iso, start, end, card["punch_in"], card["punch_out"],
                 SHIFT_BREAK_MINUTES, card["pay_code"], card["paid_hours"], card["overtime_hours"],
                 card["overtime_approved_at"], card["exception"], card["manual_edit_note"], holiday,
                 _manager_approval_time(day)),
            )

        for leave_type, hours in seed.LEAVE_BALANCES[emp["employee_id"]].items():
            conn.execute("INSERT INTO leave_balances VALUES (?,?,?)", (emp["employee_id"], leave_type, hours))

    for req in seed.LEAVE_REQUESTS:
        conn.execute(
            "INSERT INTO leave_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (req["request_id"], req["employee_id"], req["leave_type"], req["start_date"], req["end_date"],
             req["hours"], req["status"], req["submitted_at"], req["decided_at"], req["approver_id"], None),
        )

    _build_pay_statements(conn)

    # Zendesk-style ticket ids start at 10001
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('tickets', 10000)")
    conn.commit()
    conn.close()
    return db_path


def _build_pay_statements(conn: sqlite3.Connection) -> None:
    for emp in seed.EMPLOYEES:
        for period_start, period_end, pay_date, cutoff in seed.PAY_PERIODS:
            if period_end not in seed.PAID_PERIOD_ENDS:
                continue
            rows = conn.execute(
                "SELECT * FROM timecards WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
                (emp["employee_id"], period_start.isoformat(), period_end.isoformat()),
            ).fetchall()
            adjustments = seed.MANUAL_ADJUSTMENTS.get((emp["employee_id"], period_end.isoformat()))
            statement = build_pay_statement(emp["base_rate"], [dict(r) for r in rows], cutoff, adjustments)

            statement_id = f"PS-{emp['employee_id']}-{period_end.strftime('%Y%m%d')}"
            conn.execute(
                "INSERT INTO pay_statements VALUES (?,?,?,?,?,?,?,?,?,?)",
                (statement_id, emp["employee_id"], period_start.isoformat(), period_end.isoformat(),
                 pay_date.isoformat(), emp["base_rate"], statement["gross"], statement["tax_withheld"],
                 statement["net"], statement["super_contribution"]),
            )
            for line_no, line in enumerate(statement["lines"], start=1):
                conn.execute(
                    "INSERT INTO pay_lines (statement_id, line_no, code, description, hours, rate, quantity,"
                    " amount) VALUES (?,?,?,?,?,?,?,?)",
                    (statement_id, line_no, line["code"], line["description"], line["hours"], line["rate"],
                     line.get("quantity"), line["amount"]),
                )


if __name__ == "__main__":
    from helpdesk.config import WFM_DB_PATH

    print(f"Built {build_database(WFM_DB_PATH)}")
