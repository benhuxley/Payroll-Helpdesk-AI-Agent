"""Mock WFM / payroll REST API (FastAPI + SQLite).

This plays the role of the customer's system of record. The agent only ever reaches it over HTTP
through `helpdesk.integrations.wfm_client`, the same way a real deployment would call UKG or a payroll API.

Run it on its own:  uvicorn helpdesk.wfm_api.app:create_app --factory --port 8001
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from helpdesk import config
from helpdesk.wfm_api.db import build_database, connect
from helpdesk.wfm_api.pay_engine import PAY_CODES
from helpdesk.wfm_api.seed_data import PAY_PERIODS
from helpdesk.wfm_api.zendesk_mock import router as zendesk_router

LEAVE_TYPES = {"annual", "personal", "long_service"}


class VerifyRequest(BaseModel):
    employee_id: str
    date_of_birth: str
    postcode: str


class LeaveRequestIn(BaseModel):
    leave_type: str
    start_date: date
    end_date: date
    notes: str | None = None


def create_app(db_path: Path | str | None = None, api_key: str | None = None) -> FastAPI:
    db_path = Path(db_path or config.WFM_DB_PATH)
    if not db_path.exists():
        build_database(db_path)

    app = FastAPI(title="Kestrel Bay Health - mock WFM & payroll API (synthetic data)")
    app.state.db_path = db_path
    app.state.api_key = api_key or config.WFM_API_KEY

    def check_api_key(request: Request, x_api_key: str | None = Header(default=None)):
        if x_api_key != request.app.state.api_key:
            raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})

    def db(request: Request):
        conn = connect(request.app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def get_employee(conn, employee_id: str) -> dict:
        row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "employee_not_found"})
        return dict(row)

    def full_name(conn, employee_id: str | None) -> str | None:
        if not employee_id:
            return None
        row = conn.execute("SELECT first_name, last_name FROM employees WHERE employee_id = ?",
                           (employee_id,)).fetchone()
        return f"{row['first_name']} {row['last_name']}" if row else None

    secured = [Depends(check_api_key)]

    # --- identity -------------------------------------------------------------------------------
    @app.post("/api/v1/identity/verify", dependencies=secured)
    def verify_identity(body: VerifyRequest, conn=Depends(db)):
        row = conn.execute("SELECT * FROM employees WHERE employee_id = ?",
                           (body.employee_id.strip().upper(),)).fetchone()
        matched = (row is not None and row["date_of_birth"] == body.date_of_birth.strip()
                   and row["postcode"] == body.postcode.strip())
        # Never say *which* field was wrong - that would help someone guess.
        if not matched:
            return {"verified": False}
        return {"verified": True, "employee_id": row["employee_id"], "first_name": row["first_name"]}

    # --- directory (service-to-service, used by the guardrails, never exposed as an agent tool) ------
    @app.get("/api/v1/directory", dependencies=secured)
    def directory(conn=Depends(db)):
        rows = conn.execute("SELECT employee_id, first_name, last_name, manager_id FROM employees").fetchall()
        return {"employees": [dict(r) for r in rows]}

    # --- employee profile -----------------------------------------------------------------------
    @app.get("/api/v1/employees/{employee_id}", dependencies=secured)
    def employee_profile(employee_id: str, conn=Depends(db)):
        emp = get_employee(conn, employee_id)
        return {
            "employee_id": emp["employee_id"], "name": f"{emp['first_name']} {emp['last_name']}",
            "position": emp["position"], "department": emp["department"],
            "employment_type": emp["employment_type"], "base_rate": emp["base_rate"],
            "manager_name": full_name(conn, emp["manager_id"]),
        }

    # --- pay statements -------------------------------------------------------------------------
    def statement_payload(conn, row) -> dict:
        lines = conn.execute(
            "SELECT code, description, hours, rate, quantity, amount FROM pay_lines"
            " WHERE statement_id = ? ORDER BY line_no", (row["statement_id"],)).fetchall()
        payload = dict(row)
        payload["employee_name"] = full_name(conn, row["employee_id"])
        payload["lines"] = [{k: v for k, v in dict(line).items() if v is not None} for line in lines]
        return payload

    @app.get("/api/v1/employees/{employee_id}/pay-statements", dependencies=secured)
    def list_pay_statements(employee_id: str, conn=Depends(db)):
        get_employee(conn, employee_id)
        rows = conn.execute(
            "SELECT statement_id, period_start, period_end, pay_date, gross, net FROM pay_statements"
            " WHERE employee_id = ? ORDER BY period_end DESC", (employee_id,)).fetchall()
        return {"pay_statements": [dict(r) for r in rows]}

    @app.get("/api/v1/employees/{employee_id}/pay-statements/{period_end}", dependencies=secured)
    def get_pay_statement(employee_id: str, period_end: str, conn=Depends(db)):
        get_employee(conn, employee_id)
        if period_end == "latest":
            row = conn.execute("SELECT * FROM pay_statements WHERE employee_id = ?"
                               " ORDER BY period_end DESC LIMIT 1", (employee_id,)).fetchone()
        else:
            # Accept any date inside the period, not just the exact period end.
            row = conn.execute("SELECT * FROM pay_statements WHERE employee_id = ?"
                               " AND ? BETWEEN period_start AND period_end", (employee_id, period_end)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "pay_statement_not_found",
                                                         "hint": "List statements to see available periods."})
        return statement_payload(conn, row)

    # --- timecards ------------------------------------------------------------------------------
    @app.get("/api/v1/employees/{employee_id}/timecards", dependencies=secured)
    def get_timecards(employee_id: str, start: date | None = None, end: date | None = None,
                      conn=Depends(db)):
        get_employee(conn, employee_id)
        if start is None or end is None:
            start, end = _latest_paid_period()
        rows = conn.execute(
            "SELECT * FROM timecards WHERE employee_id = ? AND work_date BETWEEN ? AND ? ORDER BY work_date",
            (employee_id, start.isoformat(), end.isoformat())).fetchall()
        days = []
        for r in rows:
            day = date.fromisoformat(r["work_date"])
            entry = {
                "date": r["work_date"], "day": day.strftime("%A"),
                "rostered_shift": f"{r['rostered_start']}-{r['rostered_end']}" if r["rostered_start"] else None,
                "punch_in": r["punch_in"], "punch_out": r["punch_out"],
                "unpaid_break_minutes": r["break_minutes"] or None,
                "pay_code": r["pay_code"], "pay_code_description": PAY_CODES[r["pay_code"]][0],
                "paid_hours": r["paid_hours"],
                "overtime_hours": r["overtime_hours"] or None,
                "overtime_approved_at": r["overtime_approved_at"],
                "exception": r["exception"], "manual_edit_note": r["manual_edit_note"],
                "public_holiday": r["public_holiday"], "manager_approved_at": r["approved_at"],
            }
            days.append({k: v for k, v in entry.items() if v is not None})
        return {"employee_id": employee_id, "start": start.isoformat(), "end": end.isoformat(),
                "pay_periods": _periods_overlapping(start, end), "days": days}

    # --- roster ---------------------------------------------------------------------------------
    @app.get("/api/v1/employees/{employee_id}/roster", dependencies=secured)
    def get_roster(employee_id: str, start: date | None = None, end: date | None = None, conn=Depends(db)):
        get_employee(conn, employee_id)
        start = start or config.AS_OF_DATE
        end = end or start + timedelta(days=13)
        rows = conn.execute(
            "SELECT shift_date, start_time, end_time, break_minutes, hours, location FROM rosters"
            " WHERE employee_id = ? AND shift_date BETWEEN ? AND ? ORDER BY shift_date",
            (employee_id, start.isoformat(), end.isoformat())).fetchall()
        shifts = [{"date": r["shift_date"], "day": date.fromisoformat(r["shift_date"]).strftime("%A"),
                   "start": r["start_time"], "end": r["end_time"], "unpaid_break_minutes": r["break_minutes"],
                   "paid_hours": r["hours"], "location": r["location"]} for r in rows]
        return {"employee_id": employee_id, "start": start.isoformat(), "end": end.isoformat(), "shifts": shifts}

    # --- leave ----------------------------------------------------------------------------------
    def leave_summary(conn, employee_id: str) -> dict:
        balances = {r["leave_type"]: r["hours"] for r in conn.execute(
            "SELECT leave_type, hours FROM leave_balances WHERE employee_id = ?", (employee_id,))}
        pending = {lt: 0.0 for lt in balances}
        for r in conn.execute("SELECT leave_type, hours FROM leave_requests WHERE employee_id = ?"
                              " AND status = 'pending'", (employee_id,)):
            pending[r["leave_type"]] += r["hours"]
        return {lt: {"balance_hours": balances[lt], "pending_hours": pending[lt],
                     "available_hours": round(balances[lt] - pending[lt], 2)} for lt in balances}

    def request_payload(conn, row) -> dict:
        payload = dict(row)
        payload["approver_name"] = full_name(conn, row["approver_id"])
        return {k: v for k, v in payload.items() if v is not None}

    @app.get("/api/v1/employees/{employee_id}/leave/balances", dependencies=secured)
    def leave_balances(employee_id: str, conn=Depends(db)):
        get_employee(conn, employee_id)
        return {"employee_id": employee_id, "as_at": config.AS_OF_DATE.isoformat(),
                "note": "available_hours = balance_hours minus hours in pending requests",
                "balances": leave_summary(conn, employee_id)}

    @app.get("/api/v1/employees/{employee_id}/leave/requests", dependencies=secured)
    def leave_requests(employee_id: str, conn=Depends(db)):
        get_employee(conn, employee_id)
        rows = conn.execute("SELECT * FROM leave_requests WHERE employee_id = ? ORDER BY start_date DESC",
                            (employee_id,)).fetchall()
        return {"employee_id": employee_id, "requests": [request_payload(conn, r) for r in rows]}

    @app.post("/api/v1/employees/{employee_id}/leave/requests", dependencies=secured)
    def create_leave_request(employee_id: str, body: LeaveRequestIn, dry_run: bool = False, conn=Depends(db)):
        emp = get_employee(conn, employee_id)
        if body.leave_type not in LEAVE_TYPES:
            raise HTTPException(422, detail={"error": "invalid_leave_type", "allowed": sorted(LEAVE_TYPES)})
        if body.end_date < body.start_date:
            raise HTTPException(422, detail={"error": "end_before_start"})
        if body.start_date < config.AS_OF_DATE:
            raise HTTPException(422, detail={"error": "start_in_past",
                                             "message": "Backdated leave must be entered by your manager."})

        hours = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM rosters WHERE employee_id = ? AND shift_date BETWEEN ? AND ?",
            (employee_id, body.start_date.isoformat(), body.end_date.isoformat())).fetchone()[0]
        if hours == 0:
            raise HTTPException(422, detail={"error": "no_rostered_shifts",
                                             "message": "No rostered shifts in that date range."})

        overlap = conn.execute(
            "SELECT request_id FROM leave_requests WHERE employee_id = ? AND status IN ('pending','approved')"
            " AND start_date <= ? AND end_date >= ?",
            (employee_id, body.end_date.isoformat(), body.start_date.isoformat())).fetchone()
        if overlap:
            raise HTTPException(409, detail={"error": "overlapping_request", "request_id": overlap[0]})

        available = leave_summary(conn, employee_id)[body.leave_type]["available_hours"]
        if hours > available:
            raise HTTPException(422, detail={"error": "insufficient_balance", "requested_hours": hours,
                                             "available_hours": available, "leave_type": body.leave_type})

        request = {"employee_id": employee_id, "leave_type": body.leave_type,
                   "start_date": body.start_date.isoformat(), "end_date": body.end_date.isoformat(),
                   "hours": hours, "approver_name": full_name(conn, emp["manager_id"])}
        if dry_run:
            return {"dry_run": True, "would_create": request,
                    "available_hours_after": round(available - hours, 2)}

        count = conn.execute("SELECT COUNT(*) FROM leave_requests WHERE request_id LIKE 'LR-3%'").fetchone()[0]
        request_id = f"LR-{3001 + count}"
        submitted_at = f"{config.AS_OF_DATE.isoformat()}T{datetime.now().strftime('%H:%M')}"
        conn.execute(
            "INSERT INTO leave_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (request_id, employee_id, body.leave_type, request["start_date"], request["end_date"], hours,
             "pending", submitted_at, None, emp["manager_id"], body.notes))
        conn.commit()
        row = conn.execute("SELECT * FROM leave_requests WHERE request_id = ?", (request_id,)).fetchone()
        return {"created": True, "request": request_payload(conn, row)}

    app.include_router(zendesk_router)
    return app


def _latest_paid_period() -> tuple[date, date]:
    paid = [p for p in PAY_PERIODS if p[2] <= config.AS_OF_DATE]
    start, end, _, _ = paid[-1]
    return start, end


def _periods_overlapping(start: date, end: date) -> list[dict]:
    return [{"period_start": p[0].isoformat(), "period_end": p[1].isoformat(), "pay_date": p[2].isoformat(),
             "timecard_approval_cutoff": p[3]}
            for p in PAY_PERIODS if p[0] <= end and p[1] >= start]
