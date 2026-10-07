import requests

from .retry import classify_response, with_retries


class StateClient:
    def __init__(self, base_url: str, username: str, password: str, retries: int):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.retries = retries
        self.token = None

    def login(self) -> None:
        def operation():
            response = requests.post(
                f"{self.base_url}/api/auth/login",
                json={"username": self.username, "password": self.password}, timeout=15,
            )
            classify_response(response)
            return response.json()
        self.token = with_retries(operation, self.retries)["access_token"]

    def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            self.login()
        headers = {"Authorization": f"Bearer {self.token}"}
        def operation():
            response = requests.request(
                method, f"{self.base_url}{path}", headers=headers, timeout=15, **kwargs,
            )
            classify_response(response)
            return response.json()
        return with_retries(operation, self.retries)

    def get_state(self) -> dict:
        return self._request("GET", "/api/tracker/state")

    def get_runs(self) -> list[dict]:
        return self._request("GET", "/api/tracker/runs")

    def save_run(self, run: dict, state: dict) -> dict:
        return self._request("POST", "/api/tracker/runs", json={"run": run, "state": state})

    def reset(self) -> dict:
        return self._request("DELETE", "/api/tracker/state")

