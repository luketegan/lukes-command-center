"""Send the assignment's "Test it yourself" requests to both running workers.

Run from the project root:  python -m orchestrator.selftest
It uses a few model calls (one short research job and one or two claim checks).
"""
import json
import os
import threading
import time
import uuid

import requests
from dotenv import load_dotenv

from .run import ROOT

CLAIM_URL = "https://www.theverge.com/"


def body(payload, time_budget_ms=60000, request_id=None):
    return {"request_id": request_id or str(uuid.uuid4()), "run_id": str(uuid.uuid4()), "time_budget_ms": time_budget_ms,
            "budget": {"max_steps": 3, "max_fetches": 3, "max_tokens": 8000}, "payload": payload}


def send(url, token, data, raw=None, timeout=150):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if raw is not None:
        return requests.post(url, data=raw, headers={**headers, "Content-Type": "application/json"}, timeout=timeout)
    return requests.post(url, json=data, headers=headers, timeout=timeout)


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    return ok


def run_table(worker, url, token, good_payload, bad_payload, slow_payload):
    print(f"\n== {worker}: {url}")
    results = []
    results.append(check("no token -> 401", send(url, None, body(good_payload)).status_code == 401))
    results.append(check("wrong token -> 401", send(url, "wrong", body(good_payload)).status_code == 401))
    results.append(check("bad schema -> 400", send(url, token, body(bad_payload)).status_code == 400))

    first_body = body(good_payload, time_budget_ms=1)  # tiny budget: cheap, and also the "partial" check
    first = send(url, token, first_body)
    results.append(check("tiny time_budget_ms -> partial", first.status_code == 200 and first.json().get("status") == "partial",
                         f"got {first.status_code} {first.json().get('status') if first.ok else first.text[:120]}"))
    reordered = json.dumps(dict(reversed(list(first_body.items()))), indent=2).encode()
    second = send(url, token, None, raw=reordered)
    results.append(check("same request_id and body twice -> same response", second.status_code == first.status_code and second.json() == first.json()))
    changed = {**first_body, "time_budget_ms": 2}
    results.append(check("same request_id, different body -> 409", send(url, token, changed).status_code == 409))

    running = body(slow_payload, time_budget_ms=20000)
    holder = {}
    thread = threading.Thread(target=lambda: holder.setdefault("reply", send(url, token, running)))
    thread.start()
    time.sleep(1.5)
    duplicate = send(url, token, running)
    thread.join()
    results.append(check("same request_id while running -> 503 + Retry-After",
                         duplicate.status_code == 503 and "Retry-After" in duplicate.headers,
                         f"got {duplicate.status_code}"))
    return results


def main():
    load_dotenv(ROOT / "orchestrator" / ".env")
    researcher = os.environ["RESEARCHER_URL"].rstrip("/") + "/research"
    verifier = os.environ["VERIFIER_URL"].rstrip("/") + "/verify"
    print("Waking the verifier (a cold start can take about a minute)...")
    requests.get(os.environ["VERIFIER_URL"].rstrip("/") + "/healthz", timeout=120)
    claim = {"claim_id": "c1", "text": "The Verge publishes technology news.", "source_url": CLAIM_URL}
    results = run_table("verifier", verifier, os.environ["VERIFIER_TOKEN"], {"claims": [claim]},
                        {"claims": "not a list"}, {"claims": [claim]})
    for target in ("http://169.254.169.254/", "http://localhost/"):
        reply = send(verifier, os.environ["VERIFIER_TOKEN"], body({"claims": [{**claim, "source_url": target}]})).json()
        verdicts = (reply.get("result") or {}).get("verdicts", [])
        results.append(check(f"claim at {target} -> unreachable, no fetch",
                             verdicts[:1] == [{"claim_id": "c1", "verdict": "unreachable", "evidence": None}]
                             and reply["usage"]["fetches"] == 0))
    topic = {"topic": "festival friend-finding without cell service", "k": 3}
    results += run_table("researcher", researcher, os.environ["RESEARCHER_TOKEN"], topic, {"topic": "x"}, topic)
    print(f"\n{sum(results)} of {len(results)} checks passed")


if __name__ == "__main__":
    main()
