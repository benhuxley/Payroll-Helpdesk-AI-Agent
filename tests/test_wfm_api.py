"""The mock WFM API and its ground truth.

These tests pin the numbers the eval cases rely on. If the seed data changes, these break first,
before any eval silently starts grading against the wrong answer.
"""


def lines_by_code(statement):
    return {line["code"]: line for line in statement["lines"]}


def test_api_key_is_required(wfm_app):
    from fastapi.testclient import TestClient

    response = TestClient(wfm_app).get("/api/v1/employees/E1001/leave/balances")
    assert response.status_code == 401


def test_verify_identity(wfm_http):
    ok = wfm_http.post("/api/v1/identity/verify",
                       json={"employee_id": "E1001", "date_of_birth": "1991-03-14", "postcode": "4101"}).json()
    assert ok == {"verified": True, "employee_id": "E1001", "first_name": "Priya"}

    bad = wfm_http.post("/api/v1/identity/verify",
                        json={"employee_id": "E1001", "date_of_birth": "1991-03-15", "postcode": "4101"}).json()
    assert bad == {"verified": False}  # never reveals which field was wrong


def test_missed_punch_short_pay_e1001(wfm_http):
    latest = wfm_http.get("/api/v1/employees/E1001/pay-statements/latest").json()
    previous = wfm_http.get("/api/v1/employees/E1001/pay-statements/2026-09-27").json()
    assert latest["pay_date"] == "2026-10-14"
    assert latest["gross"] == 2970.00
    assert previous["gross"] == 3300.00
    assert lines_by_code(latest)["ORD"]["hours"] == 60.0
    assert lines_by_code(latest)["PHNW"]["hours"] == 7.5

    days = {d["date"]: d for d in wfm_http.get("/api/v1/employees/E1001/timecards").json()["days"]}
    missed = days["2026-10-06"]
    assert "punch_out" not in missed and missed["paid_hours"] == 0.0
    assert missed["exception"].startswith("MISSED_PUNCH")


def test_sunday_penalty_not_applied_e1003(wfm_http):
    latest = wfm_http.get("/api/v1/employees/E1003/pay-statements/latest").json()
    previous = wfm_http.get("/api/v1/employees/E1003/pay-statements/2026-09-27").json()
    assert "SUN" not in lines_by_code(latest)
    assert lines_by_code(latest)["ORD"]["hours"] == 45.0
    assert lines_by_code(previous)["SUN"]["hours"] == 7.5  # last fortnight it was paid correctly
    # Ground truth: 7.5h x $32.00 x (1.75 - 1.00) = $180.00 underpaid
    assert previous["gross"] - latest["gross"] == 180.00

    days = {d["date"]: d for d in wfm_http.get("/api/v1/employees/E1003/timecards").json()["days"]}
    sunday = days["2026-10-04"]
    assert sunday["day"] == "Sunday" and sunday["pay_code"] == "ORD"
    assert "manually" in sunday["manual_edit_note"]


def test_late_overtime_approval_e1004(wfm_http):
    latest = wfm_http.get("/api/v1/employees/E1004/pay-statements/latest").json()
    assert "OT150" not in lines_by_code(latest)

    timecards = wfm_http.get("/api/v1/employees/E1004/timecards").json()
    thursday = {d["date"]: d for d in timecards["days"]}["2026-10-08"]
    cutoff = timecards["pay_periods"][0]["timecard_approval_cutoff"]
    assert thursday["overtime_hours"] == 2.0
    assert thursday["overtime_approved_at"] > cutoff  # approved after cutoff -> next pay run


def test_public_holiday_worked_e1005(wfm_http):
    ph = lines_by_code(wfm_http.get("/api/v1/employees/E1005/pay-statements/latest").json())["PH"]
    assert ph == {"code": "PH", "description": "Public holiday worked 250%", "hours": 7.5, "rate": 110.0,
                  "amount": 825.0}


def test_overtime_tiers_and_meal_allowance_e1008(wfm_http):
    statement = wfm_http.get("/api/v1/employees/E1008/pay-statements/latest").json()
    lines = lines_by_code(statement)
    assert (lines["OT150"]["hours"], lines["OT150"]["amount"]) == (2.0, 105.0)
    assert (lines["OT200"]["hours"], lines["OT200"]["amount"]) == (1.0, 70.0)
    assert lines["MEAL"]["amount"] == 18.40
    assert statement["gross"] == 2818.40


def test_unexplained_adjustment_e1009(wfm_http):
    lines = lines_by_code(wfm_http.get("/api/v1/employees/E1009/pay-statements/latest").json())
    assert lines["ADJ"]["amount"] == -212.40


def test_pending_leave_reduces_available_balance_e1002(wfm_http):
    annual = wfm_http.get("/api/v1/employees/E1002/leave/balances").json()["balances"]["annual"]
    assert annual == {"balance_hours": 82.5, "pending_hours": 30.0, "available_hours": 52.5}
    pending = [r for r in wfm_http.get("/api/v1/employees/E1002/leave/requests").json()["requests"]
               if r["status"] == "pending"]
    assert pending[0]["request_id"] == "LR-2041" and pending[0]["approver_name"] == "Sofia Rossi"


def test_leave_request_dry_run_then_create_e1005(wfm_http):
    body = {"leave_type": "annual", "start_date": "2026-11-23", "end_date": "2026-11-27"}
    preview = wfm_http.post("/api/v1/employees/E1005/leave/requests?dry_run=true", json=body).json()
    assert preview["dry_run"] is True and preview["would_create"]["hours"] == 37.5
    assert wfm_http.get("/api/v1/employees/E1005/leave/requests").json()["requests"] == []  # nothing written

    created = wfm_http.post("/api/v1/employees/E1005/leave/requests", json=body).json()
    assert created["request"]["request_id"] == "LR-3001"
    assert created["request"]["status"] == "pending"


def test_insufficient_leave_balance_e1007(wfm_http):
    body = {"leave_type": "annual", "start_date": "2026-11-23", "end_date": "2026-11-27"}
    response = wfm_http.post("/api/v1/employees/E1007/leave/requests", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == {"error": "insufficient_balance", "requested_hours": 22.5,
                                         "available_hours": 12.0, "leave_type": "annual"}


def test_roster_defaults_to_next_fortnight(wfm_http):
    roster = wfm_http.get("/api/v1/employees/E1003/roster").json()
    assert roster["start"] == "2026-10-19"
    assert roster["shifts"][0]["date"] == "2026-10-21"  # first shift after "today"


def test_zendesk_mock_create_and_fetch_ticket(wfm_http):
    payload = {"ticket": {"subject": "Test", "comment": {"body": "Body"}, "priority": "high",
                          "tags": ["payroll"]}}
    assert wfm_http.post("/zendesk/api/v2/tickets.json", json=payload).status_code == 401

    auth = {"Authorization": "Basic dGVzdA=="}
    created = wfm_http.post("/zendesk/api/v2/tickets.json", json=payload, headers=auth)
    assert created.status_code == 201
    ticket = created.json()["ticket"]
    assert ticket["id"] == 10001 and ticket["status"] == "new"
    fetched = wfm_http.get(f"/zendesk/api/v2/tickets/{ticket['id']}.json", headers=auth).json()
    assert fetched["ticket"]["subject"] == "Test"
