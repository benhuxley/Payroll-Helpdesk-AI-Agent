"""HTTP client for the WFM / payroll API.

It takes any httpx.Client, so the same code runs against the real server (httpx.Client with a base_url)
or in-process against the FastAPI app (starlette's TestClient). Evals use the in-process version, so
every eval case gets its own fresh database and no ports or servers are needed.
"""

import httpx


class WFMError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(f"WFM API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class WFMClient:
    def __init__(self, http: httpx.Client):
        self.http = http

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.http.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise WFMError(response.status_code, detail)
        return response.json()

    def verify_identity(self, employee_id: str, date_of_birth: str, postcode: str) -> dict:
        return self._request("POST", "/api/v1/identity/verify", json={
            "employee_id": employee_id, "date_of_birth": date_of_birth, "postcode": postcode})

    def directory(self) -> list[dict]:
        return self._request("GET", "/api/v1/directory")["employees"]

    def list_pay_statements(self, employee_id: str) -> list[dict]:
        return self._request("GET", f"/api/v1/employees/{employee_id}/pay-statements")["pay_statements"]

    def get_pay_statement(self, employee_id: str, period: str = "latest") -> dict:
        return self._request("GET", f"/api/v1/employees/{employee_id}/pay-statements/{period}")

    def get_timecards(self, employee_id: str, start_date: str, end_date: str) -> dict:
        return self._request("GET", f"/api/v1/employees/{employee_id}/timecards",
                             params={"start": start_date, "end": end_date})

    def get_roster(self, employee_id: str, start_date: str, end_date: str) -> dict:
        return self._request("GET", f"/api/v1/employees/{employee_id}/roster",
                             params={"start": start_date, "end": end_date})

    def get_leave_balances(self, employee_id: str) -> dict:
        return self._request("GET", f"/api/v1/employees/{employee_id}/leave/balances")

    def get_leave_requests(self, employee_id: str) -> dict:
        return self._request("GET", f"/api/v1/employees/{employee_id}/leave/requests")

    def create_leave_request(self, employee_id: str, leave_type: str, start_date: str, end_date: str,
                             dry_run: bool) -> dict:
        return self._request("POST", f"/api/v1/employees/{employee_id}/leave/requests",
                             params={"dry_run": str(dry_run).lower()},
                             json={"leave_type": leave_type, "start_date": start_date, "end_date": end_date})
