"""The HTTP front door both workers share: auth, schema checks and idempotency.

Each worker passes in its own work function. Order for every POST:
1. check the service token, before reading the body;
2. parse and validate the body (400 on failure);
3. look up the request_id: replay a stored answer, refuse a changed body (409),
   or answer 503 with Retry-After while the first copy is still running;
4. run the work once, store its answer, return it.
"""
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .contract import ContractError, canonical_hash, make_error, validate_envelope

MAX_BODY_BYTES = 1_000_000


class RetryLater(Exception):
    """The work could not be done now (rate limit, overload). Answer 503; do not store."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after + 0.999))


class IdempotencyStore:
    """Answers kept in memory, keyed by request_id. They are lost when the process restarts."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries: dict[str, dict] = {}
        self.active = 0

    def begin(self, request_id: str, body_hash: str, deadline: float, max_active: int):
        with self.lock:
            entry = self.entries.get(request_id)
            if entry:
                if entry["hash"] != body_hash:
                    return "conflict", entry
                return entry["state"], entry
            if self.active >= max_active:
                return "busy", None
            entry = {"hash": body_hash, "state": "running", "deadline": deadline}
            self.entries[request_id] = entry
            self.active += 1
            return "new", entry

    def finish(self, request_id: str, code: int, body: dict, headers: dict, store: bool) -> None:
        with self.lock:
            self.active -= 1
            if store:
                self.entries[request_id].update(state="done", code=code, body=body, headers=headers)
            else:
                self.entries.pop(request_id, None)


def make_handler(*, service: str, token: str, routes: dict, trace, store: IdempotencyStore, max_active: int = 1):
    """routes maps a path to (validate_payload, work). work(envelope, deadline, trace) -> (code, body)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"{service}/1.0"
        protocol_version = "HTTP/1.0"  # one request per connection; an unread body cannot leak into the next

        def log_message(self, *args):  # Our own trace log replaces the default access log.
            pass

        def _send(self, code: int, body: dict, headers: dict | None = None) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode())

        def _reject(self, code: int, error_code: str, message: str) -> None:
            self._send(code, {"status": "failed", "error": make_error(error_code, message, False)})

        def do_GET(self):
            if self.path == "/healthz":
                self._send(200, {"status": "ok"})
                return
            if self.path.startswith("/traces/"):
                if not self._authorized():
                    self._reject(401, "unauthorized", "Missing or wrong service token")
                    return
                self._send(200, {"events": trace.for_run(self.path.removeprefix("/traces/"))})
                return
            self._reject(404, "not_found", "No such endpoint")

        def do_POST(self):
            received = time.monotonic()
            route = routes.get(self.path)
            ids = {"run_id": None, "request_id": None}

            def log(status, code, **extra):
                trace.write(**ids, step=0, direction="in", endpoint_or_tool=self.path,
                            status=status, latency_ms=(time.monotonic() - received) * 1000,
                            http_status=code, **extra)

            # 1. The token is checked first, so an unauthenticated caller learns nothing about the schema.
            if not self._authorized():
                self._reject(401, "unauthorized", "Missing or wrong service token")
                log("unauthorized", 401)
                return
            if route is None:
                self._reject(404, "not_found", "No such endpoint")
                log("not_found", 404)
                return
            # 2. Parse and validate the body.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise ContractError("Body must be JSON under 1 MB")
                envelope = json.loads(self.rfile.read(length))
                validate_payload, work = route
                validate_envelope(envelope, validate_payload)
            except (ContractError, ValueError) as exc:
                self._reject(400, "bad_request", str(exc))
                log("bad_request", 400)
                return
            ids = {"run_id": envelope["run_id"], "request_id": envelope["request_id"]}
            # The worker's clock starts when the request arrives.
            deadline = received + envelope["time_budget_ms"] / 1000
            # 3. Idempotency, keyed by request_id and compared on the parsed body.
            state, entry = store.begin(envelope["request_id"], canonical_hash(envelope), deadline, max_active)
            if state == "conflict":
                self._reject(409, "request_id_reused", "This request_id was already used with a different body")
                log("conflict", 409)
                return
            if state == "running":
                wait = max(1, int(entry["deadline"] - time.monotonic() + 1))
                self._send(503, {"status": "failed", "error": make_error("still_running", "The first copy of this request is still running", True)}, {"Retry-After": min(wait, 30)})
                log("duplicate_running", 503)
                return
            if state == "done":
                self._send(entry["code"], entry["body"], entry["headers"])
                log("replayed", entry["code"])
                return
            if state == "busy":
                self._send(503, {"status": "failed", "error": make_error("overloaded", "Another request is being processed", True)}, {"Retry-After": 15})
                log("overloaded", 503)
                return
            # 4. Do the work once.
            try:
                code, body = work(envelope, deadline, trace)
                headers, keep = {}, True
            except RetryLater as exc:
                code = 503
                body = {"request_id": envelope["request_id"], "run_id": envelope["run_id"], "status": "failed",
                        "usage": {"steps": 0, "fetches": 0, "tokens": 0}, "result": None,
                        "error": make_error("rate_limited", str(exc), True)}
                headers, keep = {"Retry-After": exc.retry_after}, False
            except Exception as exc:  # A bug must still produce an answer, not a dropped connection.
                code = 500
                body = {"request_id": envelope["request_id"], "run_id": envelope["run_id"], "status": "failed",
                        "usage": {"steps": 0, "fetches": 0, "tokens": 0}, "result": None,
                        "error": make_error("internal_error", f"{type(exc).__name__}: {exc}", False)}
                headers, keep = {}, True
            store.finish(envelope["request_id"], code, body, headers, keep)
            self._send(code, body, headers)
            usage = body.get("usage") or {}
            log(body.get("status", "failed"), code, tokens=usage.get("tokens") or 0)

    return Handler


def serve(handler, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
