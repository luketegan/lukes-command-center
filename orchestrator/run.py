"""The orchestrator: plain code that runs one research-and-verify cycle.

It is the only part that reads or writes saved state (run history and last
run's top K, in the A1 MongoDB database through the A1 backend).
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from shared.contract import validate_research_result, validate_verify_result
from shared.tracelog import TraceLog

from .report import build_report
from .workers import build_envelope, call_worker

ROOT = Path(__file__).resolve().parent.parent
BUDGET_KEYS = ("max_steps", "max_fetches", "max_tokens")
USAGE_KEYS = {"max_steps": "steps", "max_fetches": "fetches", "max_tokens": "tokens"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path = ROOT / "orchestrator" / "config.yaml") -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in BUDGET_KEYS:
        planned = sum(config["shares"][worker][key] for worker in ("researcher", "verifier"))
        if planned > config["budget"][key]:
            raise SystemExit(f"config.yaml: shares of {key} ({planned}) exceed the run total ({config['budget'][key]})")
    return config


class RunBudget:
    """Adds up what the workers report and refuses to go past the run's total."""

    def __init__(self, total: dict):
        self.total = dict(total)
        self.charged: dict[str, dict] = {}

    def charge(self, request_id: str, usage: dict) -> None:
        # Counted once per request_id, even if a retry returned a stored copy.
        self.charged.setdefault(request_id, {key: int(usage.get(key, 0)) for key in BUDGET_KEYS})

    def used(self) -> dict:
        return {key: sum(row[key] for row in self.charged.values()) for key in BUDGET_KEYS}

    def share(self, planned: dict) -> dict:
        used = self.used()
        return {key: max(0, min(planned[key], self.total[key] - used[key])) for key in BUDGET_KEYS}


def charge_call(budget: RunBudget, call, share: dict) -> None:
    if call.response is not None:
        usage = call.response["usage"]
        budget.charge(call.request_id, {key: usage[USAGE_KEYS[key]] for key in BUDGET_KEYS})
    else:
        # No trustworthy answer: we cannot know what it spent, so charge its whole share.
        budget.charge(call.request_id, share)


class Backend:
    """The A1 backend, which stores tracker state in MongoDB for the logged-in user."""

    def __init__(self, base_url: str, username: str, password: str, trace, run_id: str):
        self.base_url = base_url.rstrip("/")
        self.username, self.password = username, password
        self.trace, self.run_id = trace, run_id
        self.token = None

    def _call(self, method: str, path: str, **kwargs):
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=20, **kwargs)
            status = response.status_code
        except requests.RequestException as exc:
            status = type(exc).__name__
            raise
        finally:
            self.trace.write(run_id=self.run_id, request_id=None, step=0, direction="out",
                             endpoint_or_tool=f"backend {method} {path}", status=status,
                             latency_ms=(time.monotonic() - started) * 1000)
        response.raise_for_status()
        return response.json()

    def login(self) -> None:
        self.token = self._call("POST", "/api/auth/login", json={"username": self.username, "password": self.password})["access_token"]

    def state(self) -> dict:
        return self._call("GET", "/api/tracker/state")

    def save(self, run: dict, state: dict) -> None:
        self._call("POST", "/api/tracker/runs", json={"run": run, "state": state})


def warm_up(url: str, timeout: float, trace, run_id: str) -> threading.Thread:
    """Wake a sleeping Render instance while the researcher works, so the verify call doesn't pay for it."""
    def ping():
        started = time.monotonic()
        try:
            status = requests.get(url, timeout=timeout).status_code
        except requests.RequestException as exc:
            status = type(exc).__name__
        trace.write(run_id=run_id, request_id=None, step=0, direction="out", endpoint_or_tool="verifier GET /healthz",
                    status=status, latency_ms=(time.monotonic() - started) * 1000)
    thread = threading.Thread(target=ping, daemon=True)
    thread.start()
    return thread


def label_claims(developments: list[dict], verdicts: dict) -> list[dict]:
    labeled = []
    for item in developments:
        claims = []
        for claim in item["claims"]:
            verdict = verdicts.get(claim["claim_id"])
            claims.append({**claim, "label": verdict["verdict"] if verdict else "unverified",
                           "evidence": verdict["evidence"] if verdict else None})
        labeled.append({**item, "key": item["id"], "claims": claims})
    return labeled


def counts_toward_top_k(item: dict) -> bool:
    """A development stays in the ranking unless the verifier rejected every one of its claims."""
    return any(claim["label"] in ("supported", "unverified") for claim in item["claims"])


def next_run_number(folder: Path) -> int:
    numbers = [int(m.group(1)) for p in folder.glob("run*.md") if (m := re.fullmatch(r"run(\d+)", p.stem))]
    return max(numbers, default=0) + 1


def run(config: dict | None = None, env: dict | None = None, *, sleep=time.sleep) -> Path:
    config = config or load_config()
    env = env if env is not None else os.environ
    run_id = str(uuid.uuid4())
    started_at = now_iso()
    reports = ROOT / "reports" / "orchestrated"
    number = next_run_number(reports)
    trace = TraceLog("orchestrator", ROOT / "traces" / "orchestrator")
    budget = RunBudget(config["budget"])
    failed_workers: dict[str, str] = {}
    worker_status: dict[str, str] = {}
    timeouts, retry = config["timeouts"], config["retries"]

    backend = Backend(env.get("BACKEND_URL", "http://127.0.0.1:8000"), env["TRACKER_USERNAME"],
                      env["TRACKER_PASSWORD"], trace, run_id)
    backend.login()
    previous = backend.state()
    verifier_url = env["VERIFIER_URL"].rstrip("/")
    warm_up(f"{verifier_url}/healthz", timeouts["verifier_cold_start_seconds"] + 15, trace, run_id)

    # 1. Research.
    research_share = budget.share(config["shares"]["researcher"])
    research_env = build_envelope(run_id, config["time_budget_ms"]["researcher"], research_share,
                                  {"topic": config["topic"], "k": config["k"]})
    research = call_worker(
        worker="researcher", url=f"{env['RESEARCHER_URL'].rstrip('/')}/research", token=env["RESEARCHER_TOKEN"],
        envelope=research_env, retry=retry, validate_result=validate_research_result, trace=trace, sleep=sleep,
        timeout=config["time_budget_ms"]["researcher"] / 1000 + timeouts["grace_seconds"])
    charge_call(budget, research, research_share)
    developments = []
    if research.response is not None and research.response["status"] != "failed":
        developments = research.response["result"]["developments"]
        worker_status["researcher"] = research.response["status"]
        if research.response["status"] == "partial":
            worker_status["researcher_note"] = research.response["error"]["message"]
    else:
        failed_workers["researcher"] = research.failure or "failed"

    # 2. Verify. The verifier gets only claim ids, claim text and URLs.
    claims = [{"claim_id": c["claim_id"], "text": c["text"], "source_url": c["source_url"]}
              for item in developments for c in item["claims"]]
    verdicts = {}
    if claims:
        verify_share = budget.share(config["shares"]["verifier"])
        if min(verify_share["max_steps"], verify_share["max_fetches"]) <= 0:
            failed_workers["verifier"] = "not called: the run's budget was already spent"
        else:
            verify_env = build_envelope(run_id, config["time_budget_ms"]["verifier"], verify_share, {"claims": claims})
            sent = {claim["claim_id"] for claim in claims}
            verify = call_worker(
                worker="verifier", url=f"{verifier_url}/verify", token=env["VERIFIER_TOKEN"], envelope=verify_env,
                retry=retry, validate_result=lambda result: validate_verify_result(result, sent),
                trace=trace, sleep=sleep,
                timeout=config["time_budget_ms"]["verifier"] / 1000 + timeouts["grace_seconds"]
                + timeouts["verifier_cold_start_seconds"])
            charge_call(budget, verify, verify_share)
            if verify.response is not None and verify.response["status"] != "failed":
                verdicts = {row["claim_id"]: row for row in verify.response["result"]["verdicts"]}
                worker_status["verifier"] = verify.response["status"]
                if verify.response["status"] == "partial":
                    worker_status["verifier_note"] = verify.response["error"]["message"]
            else:
                failed_workers["verifier"] = verify.failure or "failed"

    # 3. Rank, compare with last run, report.
    previous_items = {item.get("key") or item.get("id"): item for item in previous.get("developments", [])}
    last_top = [key for key in previous.get("last_top_k", []) if key in previous_items]
    stale = "researcher" in failed_workers
    if stale:
        top, new_items, dropped = [previous_items[key] for key in last_top], [], []
        still = top
        rejected = []
        state_developments, top_keys = list(previous_items.values()), last_top
    else:
        labeled = label_claims(developments, verdicts)
        ranked = [item for item in labeled if counts_toward_top_k(item)]
        rejected = [item for item in labeled if not counts_toward_top_k(item)]
        top = ranked[: config["k"]]
        top_keys = [item["key"] for item in top]
        new_items = [item for item in top if item["key"] not in last_top]
        still = [item for item in top if item["key"] in last_top]
        dropped = [previous_items[key] for key in last_top if key not in top_keys]
        state_developments = top + [item for key, item in previous_items.items() if key not in top_keys][:20]
    partial = bool(failed_workers) or any(value == "partial" for key, value in worker_status.items() if not key.endswith("note"))
    status = "partial" if partial else "complete"
    completed_at = now_iso()
    report = build_report(config=config, run_number=number, run_id=run_id, status=status, stale=stale,
                          new_items=new_items, still_items=still, dropped_items=dropped, rejected=rejected,
                          failed_workers=failed_workers, worker_status=worker_status, used=budget.used(),
                          total=config["budget"], completed_at=completed_at)
    reports.mkdir(parents=True, exist_ok=True)
    report_path = reports / f"run{number}.md"
    report_path.write_text(report, encoding="utf-8")

    checked = [{"title": claim["text"][:200], "url": claim["source_url"], "time": completed_at,
                "status": claim["label"]} for item in (top + rejected) if not stale for claim in item["claims"]]
    run_record = {
        "run_id": run_id, "started_at": started_at, "completed_at": completed_at, "status": status,
        "topic": config["topic"], "k": config["k"], "model": "orchestrated: researcher + verifier",
        "new_items": new_items, "still_items": still, "dropped_items": dropped, "articles": checked,
        "budget_usage": budget.used(), "report_markdown": report,
        "stop_reason": "; ".join(f"{name}: {why}" for name, why in failed_workers.items()) or None,
        "failed_workers": sorted(failed_workers), "stale": stale,
    }
    next_state = {"topic": config["topic"], "seen_urls": sorted({c["source_url"] for i in state_developments for c in i.get("claims", [])}),
                  "developments": state_developments, "last_top_k": top_keys, "updated_at": completed_at}
    try:
        backend.save(run_record, next_state)
    except requests.RequestException as exc:
        print(f"Warning: the report was written, but saving to the backend failed: {exc}")
    export_traces(number, run_id, trace, env, verifier_url)
    print(f"Saved {report_path}; status={status}; failed workers: {', '.join(failed_workers) or 'none'}")
    return report_path


def export_traces(number: int, run_id: str, trace, env, verifier_url: str) -> None:
    """Gather all three logs for this run into traces/orchestrated/runN/."""
    folder = ROOT / "traces" / "orchestrated" / f"run{number}"
    folder.mkdir(parents=True, exist_ok=True)
    sources = {"orchestrator": trace.for_run(run_id)}
    for name, base, token in (("researcher", env["RESEARCHER_URL"], env["RESEARCHER_TOKEN"]),
                              ("verifier", verifier_url, env["VERIFIER_TOKEN"])):
        try:
            reply = requests.get(f"{base.rstrip('/')}/traces/{run_id}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
            sources[name] = reply.json().get("events", []) if reply.ok else []
        except (requests.RequestException, ValueError):
            sources[name] = []
    for name, events in sources.items():
        with (folder / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
