"""Calling a worker over HTTP: one logical request, retried safely."""
import json
import time
import uuid
from urllib.parse import urlsplit

import requests

from shared.contract import ContractError, retry_after_seconds, validate_response

TRANSIENT_CODES = {503}


class WorkerCall:
    """The outcome of one logical request (one request_id), across all its attempts."""

    def __init__(self, worker: str, request_id: str):
        self.worker = worker
        self.request_id = request_id
        self.response = None  # a validated response body, or None
        self.failure = None  # why the worker counts as failed, or None
        self.attempts = 0


def build_envelope(run_id: str, time_budget_ms: int, budget: dict, payload: dict) -> dict:
    return {
        "request_id": str(uuid.uuid4()),  # one per logical request, reused on every retry
        "run_id": run_id,
        "time_budget_ms": int(time_budget_ms),
        "budget": {key: int(budget[key]) for key in ("max_steps", "max_fetches", "max_tokens")},
        "payload": payload,
    }


def call_worker(*, worker: str, url: str, token: str, envelope: dict, timeout: float, retry: dict,
                validate_result, trace, sleep=time.sleep) -> WorkerCall:
    outcome = WorkerCall(worker, envelope["request_id"])
    # The exact same bytes go out on every attempt, so a retry is never a different request.
    data = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ids = {"run_id": envelope["run_id"], "request_id": envelope["request_id"]}
    endpoint = f"{worker} POST {urlsplit(url).path}"

    for attempt in range(1, int(retry["max_attempts"]) + 1):
        outcome.attempts = attempt
        started = time.monotonic()
        wait, reason = None, None
        try:
            reply = requests.post(url, data=data, headers=headers, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = f"{type(exc).__name__} after {time.monotonic() - started:.1f}s"
            trace.write(**ids, step=0, direction="out", endpoint_or_tool=endpoint, status="transient_error",
                        latency_ms=(time.monotonic() - started) * 1000, attempt=attempt, detail=reason)
        else:
            latency = (time.monotonic() - started) * 1000
            if reply.status_code in TRANSIENT_CODES:
                reason = f"HTTP {reply.status_code}"
                wait = retry_after_seconds(reply.headers.get("Retry-After"), default=None)
                trace.write(**ids, step=0, direction="out", endpoint_or_tool=endpoint, status="retry_later",
                            latency_ms=latency, attempt=attempt, http_status=reply.status_code)
            elif reply.status_code == 200 or reply.status_code == 500:
                try:
                    body = validate_response(reply.json(), request_id=envelope["request_id"],
                                             run_id=envelope["run_id"], validate_result=validate_result)
                except (ContractError, ValueError) as exc:
                    # A malformed answer counts as the worker failing. Its contents go no further.
                    outcome.failure = f"malformed response: {exc}"
                    trace.write(**ids, step=0, direction="out", endpoint_or_tool=endpoint, status="malformed",
                                latency_ms=latency, attempt=attempt, http_status=reply.status_code)
                    return outcome
                tokens = body["usage"]["tokens"]
                trace.write(**ids, step=0, direction="out", endpoint_or_tool=endpoint, status=body["status"],
                            latency_ms=latency, attempt=attempt, tokens=tokens, http_status=reply.status_code)
                outcome.response = body
                if reply.status_code == 500:
                    outcome.failure = f"worker failed: {body['error']['message']}"
                return outcome
            else:
                # 400, 401, 409 and anything unexpected: retrying cannot fix it.
                outcome.failure = f"HTTP {reply.status_code}: {reply.text[:200]}"
                trace.write(**ids, step=0, direction="out", endpoint_or_tool=endpoint, status="terminal_error",
                            latency_ms=latency, attempt=attempt, http_status=reply.status_code)
                return outcome
        if attempt < int(retry["max_attempts"]):
            backoff = min(float(retry["base_delay_seconds"]) * 2 ** (attempt - 1), float(retry["max_delay_seconds"]))
            sleep(min(wait, float(retry["max_delay_seconds"])) if wait is not None else backoff)
        outcome.failure = f"no answer after {attempt} attempts ({reason})"
    return outcome
