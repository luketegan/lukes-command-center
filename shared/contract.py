"""The wire contract shared by the orchestrator, researcher and verifier.

This file only describes and checks messages. No service calls another
service's code through it: they talk over HTTP and use this to agree on shapes.
"""
import hashlib
import json
import math
import re
import uuid
from urllib.parse import urlsplit

BUDGET_KEYS = ("max_steps", "max_fetches", "max_tokens")
STATUSES = ("complete", "partial", "failed")
VERDICTS = ("supported", "unsupported", "unreachable")
MAX_EVIDENCE_CHARS = 300


class ContractError(ValueError):
    """A message that does not match the contract."""


def canonical_hash(body) -> str:
    """The same JSON once parsed gives the same hash, whatever the key order or spacing."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact_keys(value, required: set, name: str, optional: set = frozenset()) -> None:
    _require(isinstance(value, dict), f"{name} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    _require(not missing, f"{name} is missing {sorted(missing)}")
    _require(not extra, f"{name} has unknown fields {sorted(extra)}")


def _uuid(value, name: str) -> None:
    try:
        _require(isinstance(value, str) and str(uuid.UUID(value)) == value.lower(), f"{name} must be a UUID")
    except ValueError as exc:
        raise ContractError(f"{name} must be a UUID") from exc


def _int(value, name: str, low: int, high: int) -> None:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{name} must be an integer")
    _require(low <= value <= high, f"{name} must be between {low} and {high}")


def _text(value, name: str, max_len: int) -> None:
    _require(isinstance(value, str) and value.strip() != "", f"{name} must be a non-empty string")
    _require(len(value) <= max_len, f"{name} is longer than {max_len} characters")


def _url(value, name: str) -> None:
    _text(value, name, 2048)
    parts = urlsplit(value)
    _require(parts.scheme in ("http", "https") and bool(parts.netloc), f"{name} must be an http(s) URL")


def validate_envelope(body, validate_payload) -> dict:
    """Check a worker request. Returns the body unchanged so callers can use it."""
    _exact_keys(body, {"request_id", "run_id", "time_budget_ms", "budget", "payload"}, "request")
    _uuid(body["request_id"], "request_id")
    _uuid(body["run_id"], "run_id")
    _int(body["time_budget_ms"], "time_budget_ms", 1, 900_000)
    _exact_keys(body["budget"], set(BUDGET_KEYS), "budget")
    _int(body["budget"]["max_steps"], "budget.max_steps", 0, 1000)
    _int(body["budget"]["max_fetches"], "budget.max_fetches", 0, 1000)
    _int(body["budget"]["max_tokens"], "budget.max_tokens", 0, 10_000_000)
    validate_payload(body["payload"])
    return body


def validate_research_payload(payload) -> None:
    _exact_keys(payload, {"topic", "k"}, "payload")
    _text(payload["topic"], "payload.topic", 1000)
    _int(payload["k"], "payload.k", 1, 20)


def validate_verify_payload(payload) -> None:
    _exact_keys(payload, {"claims"}, "payload")
    claims = payload["claims"]
    _require(isinstance(claims, list) and 1 <= len(claims) <= 100, "payload.claims must hold 1 to 100 claims")
    seen = set()
    for index, claim in enumerate(claims):
        name = f"payload.claims[{index}]"
        _exact_keys(claim, {"claim_id", "text", "source_url"}, name)
        _text(claim["claim_id"], f"{name}.claim_id", 100)
        _text(claim["text"], f"{name}.text", 2000)
        _url(claim["source_url"], f"{name}.source_url")
        _require(claim["claim_id"] not in seen, f"{name}.claim_id is repeated")
        seen.add(claim["claim_id"])


def validate_research_result(result) -> None:
    _exact_keys(result, {"developments"}, "result")
    developments = result["developments"]
    _require(isinstance(developments, list) and len(developments) <= 50, "result.developments must be a list")
    claim_ids, development_ids = set(), set()
    for index, item in enumerate(developments):
        name = f"result.developments[{index}]"
        _exact_keys(item, {"id", "title", "summary", "claims"}, name)
        _text(item["id"], f"{name}.id", 200)
        _require(item["id"] not in development_ids, f"{name}.id is repeated")
        development_ids.add(item["id"])
        _text(item["title"], f"{name}.title", 500)
        _text(item["summary"], f"{name}.summary", 3000)
        _require(isinstance(item["claims"], list) and item["claims"], f"{name}.claims must not be empty")
        for claim_index, claim in enumerate(item["claims"]):
            claim_name = f"{name}.claims[{claim_index}]"
            _exact_keys(claim, {"claim_id", "text", "source_url"}, claim_name)
            _text(claim["claim_id"], f"{claim_name}.claim_id", 100)
            _require(claim["claim_id"] not in claim_ids, f"{claim_name}.claim_id is repeated")
            claim_ids.add(claim["claim_id"])
            _text(claim["text"], f"{claim_name}.text", 2000)
            _url(claim["source_url"], f"{claim_name}.source_url")


def validate_verify_result(result, sent_claim_ids: set | None = None) -> None:
    _exact_keys(result, {"verdicts"}, "result")
    verdicts = result["verdicts"]
    _require(isinstance(verdicts, list), "result.verdicts must be a list")
    seen = set()
    for index, verdict in enumerate(verdicts):
        name = f"result.verdicts[{index}]"
        _exact_keys(verdict, {"claim_id", "verdict", "evidence"}, name)
        _require(isinstance(verdict["claim_id"], str), f"{name}.claim_id must be a string")
        if sent_claim_ids is not None:
            _require(verdict["claim_id"] in sent_claim_ids, f"{name}.claim_id was never sent")
        _require(verdict["claim_id"] not in seen, f"{name}.claim_id is repeated")
        seen.add(verdict["claim_id"])
        _require(verdict["verdict"] in VERDICTS, f"{name}.verdict must be one of {VERDICTS}")
        if verdict["verdict"] == "supported":
            _text(verdict["evidence"], f"{name}.evidence", MAX_EVIDENCE_CHARS)
        else:
            _require(verdict["evidence"] is None, f"{name}.evidence must be null unless supported")


def validate_response(body, *, request_id: str, run_id: str, validate_result) -> dict:
    """Check a worker reply. The orchestrator treats any failure here as that worker failing."""
    _exact_keys(body, {"request_id", "run_id", "status", "usage", "result", "error"}, "response")
    _require(body["request_id"] == request_id, "response.request_id does not match the request")
    _require(body["run_id"] == run_id, "response.run_id does not match the run")
    _require(body["status"] in STATUSES, f"response.status must be one of {STATUSES}")
    _exact_keys(body["usage"], {"steps", "fetches", "tokens"}, "response.usage")
    for key in ("steps", "fetches", "tokens"):
        _int(body["usage"][key], f"response.usage.{key}", 0, 10_000_000)
    error = body["error"]
    if body["status"] == "complete":
        _require(error is None, "response.error must be null when complete")
    else:
        _exact_keys(error, {"code", "message", "retryable"}, "response.error")
        _require(re.fullmatch(r"[a-z_]{1,60}", str(error["code"])) is not None, "response.error.code is invalid")
        _text(error["message"], "response.error.message", 1000)
        _require(isinstance(error["retryable"], bool), "response.error.retryable must be true or false")
    if body["status"] == "failed":
        _require(body["result"] is None, "response.result must be null when failed")
    else:
        validate_result(body["result"])
    return body


def make_response(envelope: dict, status: str, usage: dict, result=None, error=None) -> dict:
    return {
        "request_id": envelope["request_id"],
        "run_id": envelope["run_id"],
        "status": status,
        "usage": {key: int(usage.get(key, 0)) for key in ("steps", "fetches", "tokens")},
        "result": result,
        "error": error,
    }


def make_error(code: str, message: str, retryable: bool) -> dict:
    return {"code": code, "message": message[:1000] or code, "retryable": retryable}


def retry_after_seconds(value, default: float = 5.0) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(seconds) or seconds < 0 else seconds
