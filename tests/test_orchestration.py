"""Agentic orchestration checks. They start real HTTP servers on random local ports but make
no calls to Groq, Tavily, Render or web pages, so they cost nothing."""
import ipaddress
import json
import threading
import time
import uuid

import pytest
import requests

from orchestrator import run as orchestrator_run
from orchestrator.workers import build_envelope, call_worker
from services.researcher import app as researcher_app
from services.verifier import app as verifier_app
from shared.contract import validate_research_result, validate_verify_result
from shared.tracelog import TraceLog
from shared.worker_http import serve

TOKEN = "test-token-" + "x" * 20
RETRY = {"max_attempts": 4, "base_delay_seconds": 0, "max_delay_seconds": 0}
PAGE = "FireChat let Coachella attendees message each other without cell service using a mesh network."


def start(handler):
    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def envelope(payload, time_budget_ms=60000, budget=None, request_id=None):
    return {"request_id": request_id or str(uuid.uuid4()), "run_id": str(uuid.uuid4()),
            "time_budget_ms": time_budget_ms, "budget": budget or {"max_steps": 10, "max_fetches": 8, "max_tokens": 40000},
            "payload": payload}


def claims_payload(*urls):
    return {"claims": [{"claim_id": f"c{i}", "text": "FireChat worked at Coachella without cell service.", "source_url": url}
                       for i, url in enumerate(urls)]}


@pytest.fixture
def verifier(monkeypatch):
    calls = {"model": 0, "fetch": 0}

    def fake_fetch(url, deadline, spend_fetch):
        verifier_app.check_url(url)
        spend_fetch()
        calls["fetch"] += 1
        return PAGE

    def fake_model(api_key, model, claim, passage, deadline):
        calls["model"] += 1
        time.sleep(calls.get("delay", 0))
        return {"verdict": "supported", "evidence": calls.get("evidence", "message each other without cell service")}, 120

    monkeypatch.setenv("VERIFIER_TOKEN", TOKEN)
    monkeypatch.setattr(verifier_app, "fetch_page", fake_fetch)
    monkeypatch.setattr(verifier_app, "ask_model", fake_model)
    monkeypatch.setattr(verifier_app, "resolve",
                        lambda host, port: [(None, None, None, "", (fake_address(host), port))])
    server, url = start(verifier_app.build_handler(trace=TraceLog("verifier"), api_key="k"))
    yield url, calls
    server.shutdown()


def fake_address(host):
    """Stand-in DNS: IP literals resolve to themselves, localhost to loopback, anything else to a public IP."""
    if host == "localhost":
        return "127.0.0.1"
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return "93.184.216.34"


def post(url, body, token=TOKEN, raw=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if raw is not None:
        return requests.post(url, data=raw, headers={**headers, "Content-Type": "application/json"}, timeout=10)
    return requests.post(url, json=body, headers=headers, timeout=10)


# ---------- the PDF's "Test it yourself" table, against the verifier ----------

def test_healthz_needs_no_token(verifier):
    url, _ = verifier
    assert requests.get(f"{url}/healthz", timeout=5).json() == {"status": "ok"}


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_missing_or_wrong_token_is_401_even_with_a_bad_body(verifier, token):
    url, _ = verifier
    reply = post(f"{url}/verify", None, token=token, raw=b"{not json")
    assert reply.status_code == 401
    assert "claims" not in reply.text  # nothing about the schema leaks


@pytest.mark.parametrize("body", [
    {"payload": {}},
    envelope({"claims": []}),
    envelope({"claims": [{"claim_id": "a", "text": "x", "source_url": "ftp://x"}]}),
    {**envelope(claims_payload("https://example.com")), "time_budget_ms": "fast"},
])
def test_schema_failures_are_400(verifier, body):
    url, _ = verifier
    assert post(f"{url}/verify", body).status_code == 400


def test_same_request_twice_returns_the_stored_answer_without_new_work(verifier):
    url, calls = verifier
    body = envelope(claims_payload("https://example.com/a"))
    first = post(f"{url}/verify", body)
    reordered = json.dumps(dict(reversed(list(body.items()))), indent=4).encode()  # same JSON, different bytes
    second = post(f"{url}/verify", None, raw=reordered)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == {"model": 1, "fetch": 1}


def test_same_request_id_with_a_different_body_is_409(verifier):
    url, _ = verifier
    body = envelope(claims_payload("https://example.com/a"))
    post(f"{url}/verify", body)
    changed = {**body, "time_budget_ms": body["time_budget_ms"] - 1}
    assert post(f"{url}/verify", changed).status_code == 409


def test_duplicate_while_running_is_503_with_retry_after(verifier):
    url, calls = verifier
    calls["delay"] = 1.0
    body = envelope(claims_payload("https://example.com/a"))
    first = {}
    thread = threading.Thread(target=lambda: first.setdefault("reply", post(f"{url}/verify", body)))
    thread.start()
    time.sleep(0.3)
    duplicate = post(f"{url}/verify", body)
    thread.join()
    assert duplicate.status_code == 503 and int(duplicate.headers["Retry-After"]) >= 1
    assert first["reply"].status_code == 200 and calls["model"] == 1


@pytest.mark.parametrize("target", ["http://169.254.169.254/", "http://localhost/", "http://[::1]/", "http://10.0.0.8/"])
def test_internal_addresses_are_unreachable_and_never_fetched(verifier, target):
    url, calls = verifier
    reply = post(f"{url}/verify", envelope(claims_payload(target))).json()
    assert reply["result"]["verdicts"] == [{"claim_id": "c0", "verdict": "unreachable", "evidence": None}]
    assert calls["fetch"] == 0 and calls["model"] == 0


def test_tiny_time_budget_returns_partial_with_what_it_had(verifier):
    url, calls = verifier
    calls["delay"] = 0.5
    body = envelope(claims_payload(*[f"https://example.com/{n}" for n in range(4)]), time_budget_ms=3000)
    reply = post(f"{url}/verify", body).json()
    assert reply["status"] == "partial"
    assert reply["error"]["code"] == "time_budget_exhausted"
    assert len(reply["result"]["verdicts"]) < 4
    validate_verify_result(reply["result"], {"c0", "c1", "c2", "c3"})


def test_made_up_evidence_becomes_unsupported(verifier):
    url, calls = verifier
    calls["evidence"] = "FireChat was used by two million people at Coachella."
    reply = post(f"{url}/verify", envelope(claims_payload("https://example.com/a"))).json()
    assert reply["result"]["verdicts"][0] == {"claim_id": "c0", "verdict": "unsupported", "evidence": None}


def test_normalization_follows_the_four_steps():
    assert verifier_app.excerpt_in_page("CELL&nbsp;Service   Using a MESH", "without cell service using a mesh network")
    assert not verifier_app.excerpt_in_page("too short", PAGE)


def test_redirect_to_metadata_address_is_blocked(monkeypatch):
    monkeypatch.setattr(verifier_app, "resolve",
                        lambda host, port: [(None, None, None, "", ("169.254.169.254" if host == "169.254.169.254" else "93.184.216.34", 80))])

    class Redirect:
        status_code, is_redirect, ok = 302, True, False
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    requested = []
    monkeypatch.setattr(verifier_app.requests, "get", lambda url, **k: requested.append(url) or Redirect())
    with pytest.raises(verifier_app.Unreachable):
        verifier_app.fetch_page("http://example.com/", time.monotonic() + 30, lambda: None)
    assert requested == ["http://example.com/"]  # the metadata address was never requested


# ---------- the researcher behind the same front door ----------

def fake_research(**kwargs):
    kwargs["trace"].write(**kwargs["ids"], step=1, direction="out", endpoint_or_tool="model", status="ok", tokens=50)
    return {"status": "complete", "usage": {"steps": 1, "fetches": 1, "tokens": 50}, "error": None,
            "developments": [{"id": "firechat", "title": "FireChat at Coachella", "summary": "Mesh chat app.",
                              "claims": [{"claim_id": "c0", "text": "FireChat worked at Coachella.", "source_url": "https://example.com/a"}]}]}


def test_researcher_contract(monkeypatch):
    monkeypatch.setenv("RESEARCHER_TOKEN", TOKEN)
    server, url = start(researcher_app.build_handler(trace=TraceLog("researcher"), research_fn=fake_research, config={}))
    try:
        assert post(f"{url}/research", envelope({"topic": "x", "k": 5}), token=None).status_code == 401
        assert post(f"{url}/research", envelope({"topic": "x"})).status_code == 400
        reply = post(f"{url}/research", envelope({"topic": "x", "k": 5})).json()
        validate_research_result(reply["result"])
        assert reply["status"] == "complete" and reply["usage"]["tokens"] == 50
    finally:
        server.shutdown()


# ---------- the orchestrator ----------

def test_retry_resends_the_same_body_and_honours_retry_after(monkeypatch):
    seen, sleeps = [], []
    body = build_envelope(str(uuid.uuid4()), 1000, {"max_steps": 1, "max_fetches": 1, "max_tokens": 1}, {"claims": []})

    class Reply:
        def __init__(self, code, data=None, headers=None):
            self.status_code, self._data, self.headers, self.text = code, data, headers or {}, ""
        def json(self): return self._data

    replies = [requests.ConnectionError("refused"),
               Reply(503, headers={"Retry-After": "7"}),
               Reply(200, {"request_id": body["request_id"], "run_id": body["run_id"], "status": "complete",
                           "usage": {"steps": 1, "fetches": 1, "tokens": 9}, "result": {"verdicts": []}, "error": None})]

    def fake_post(url, data, headers, timeout):
        seen.append(data)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(orchestrator_run.requests, "post", fake_post)
    monkeypatch.setattr("orchestrator.workers.requests.post", fake_post)
    call = call_worker(worker="verifier", url="http://w/verify", token=TOKEN, envelope=body, timeout=5,
                       retry={"max_attempts": 4, "base_delay_seconds": 2, "max_delay_seconds": 30},
                       validate_result=lambda r: validate_verify_result(r, set()), trace=TraceLog("o"), sleep=sleeps.append)
    assert call.response is not None and call.attempts == 3
    assert len(set(seen)) == 1  # identical bytes every time
    assert sleeps == [2.0, 7.0]  # backoff, then the server's Retry-After


@pytest.mark.parametrize("bad", [
    {"verdicts": [{"claim_id": "never-sent", "verdict": "supported", "evidence": "x" * 30}]},
    {"verdicts": [{"claim_id": "c0", "verdict": "supported", "evidence": None}]},
    {"verdicts": "<script>alert(1)</script>"},
])
def test_malformed_verifier_answers_count_as_failure(monkeypatch, bad):
    body = build_envelope(str(uuid.uuid4()), 1000, {"max_steps": 1, "max_fetches": 1, "max_tokens": 1}, {"claims": []})

    class Reply:
        status_code, headers, text = 200, {}, ""
        def json(self):
            return {"request_id": body["request_id"], "run_id": body["run_id"], "status": "complete",
                    "usage": {"steps": 0, "fetches": 0, "tokens": 0}, "result": bad, "error": None}
    monkeypatch.setattr("orchestrator.workers.requests.post", lambda *a, **k: Reply())
    call = call_worker(worker="verifier", url="http://w/verify", token=TOKEN, envelope=body, timeout=5, retry=RETRY,
                       validate_result=lambda r: validate_verify_result(r, {"c0"}), trace=TraceLog("o"))
    assert call.response is None and "malformed" in call.failure


def test_budget_counts_each_request_once_and_charges_a_silent_worker_its_share():
    budget = orchestrator_run.RunBudget({"max_steps": 30, "max_fetches": 24, "max_tokens": 75000})
    budget.charge("a", {"max_steps": 5, "max_fetches": 2, "max_tokens": 9000})
    budget.charge("a", {"max_steps": 5, "max_fetches": 2, "max_tokens": 9000})  # stored copy returned on retry
    class Silent: response, request_id = None, "b"
    orchestrator_run.charge_call(budget, Silent(), {"max_steps": 12, "max_fetches": 16, "max_tokens": 17000})
    assert budget.used() == {"max_steps": 17, "max_fetches": 18, "max_tokens": 26000}
    assert budget.share({"max_steps": 99, "max_fetches": 99, "max_tokens": 99999}) == {"max_steps": 13, "max_fetches": 6, "max_tokens": 49000}


class FakeBackend:
    saved = None
    previous = {"developments": [{"key": "old", "id": "old", "title": "Old item", "summary": "s",
                                  "claims": [{"claim_id": "x", "text": "t", "source_url": "https://e.com", "label": "supported", "evidence": "e"}]}],
                "last_top_k": ["old"]}

    def __init__(self, *args): pass
    def login(self): pass
    def state(self): return FakeBackend.previous
    def save(self, run, state): FakeBackend.saved = (run, state)


@pytest.fixture
def orchestrated(tmp_path, monkeypatch, verifier):
    verifier_url, _ = verifier
    monkeypatch.setenv("RESEARCHER_TOKEN", TOKEN)
    researcher_server, researcher_url = start(researcher_app.build_handler(trace=TraceLog("researcher"), research_fn=fake_research, config={}))
    monkeypatch.setattr(orchestrator_run, "ROOT", tmp_path)
    monkeypatch.setattr(orchestrator_run, "Backend", FakeBackend)
    config = orchestrator_run.load_config()
    config["time_budget_ms"] = {"researcher": 5000, "verifier": 5000}
    config["timeouts"] = {"grace_seconds": 2, "verifier_cold_start_seconds": 1}
    config["retries"] = RETRY
    env = {"RESEARCHER_URL": researcher_url, "RESEARCHER_TOKEN": TOKEN, "VERIFIER_URL": verifier_url,
           "VERIFIER_TOKEN": TOKEN, "TRACKER_USERNAME": "u", "TRACKER_PASSWORD": "p"}
    yield config, env, tmp_path
    researcher_server.shutdown()


def test_full_run_labels_claims_and_follows_one_request_across_logs(orchestrated):
    config, env, root = orchestrated
    report = orchestrator_run.run(config, env, sleep=lambda s: None).read_text()
    run, state = FakeBackend.saved
    assert run["status"] == "complete" and run["failed_workers"] == []
    assert run["new_items"][0]["claims"][0]["label"] == "supported"
    assert [item["key"] for item in run["dropped_items"]] == ["old"]
    assert "Evidence:" in report and "## New since last run" in report
    logs = {name: [json.loads(line) for line in (root / "traces" / "orchestrated" / "run1" / f"{name}.jsonl").read_text().splitlines()]
            for name in ("orchestrator", "researcher", "verifier")}
    verify_id = next(e["request_id"] for e in logs["orchestrator"] if "verifier POST" in e["endpoint_or_tool"])
    assert any(e["request_id"] == verify_id for e in logs["verifier"])
    for events in logs.values():
        for event in events:
            assert set(event) >= {"ts", "service", "run_id", "request_id", "step", "direction", "endpoint_or_tool", "status", "latency_ms", "attempt", "tokens"}
            assert TOKEN not in json.dumps(event)


def test_verifier_down_marks_claims_unverified(orchestrated):
    config, env, _ = orchestrated
    env["VERIFIER_URL"] = "http://127.0.0.1:9"  # nothing listens here
    orchestrator_run.run(config, env, sleep=lambda s: None)
    run, _ = FakeBackend.saved
    assert run["status"] == "partial" and run["failed_workers"] == ["verifier"]
    assert run["new_items"][0]["claims"][0]["label"] == "unverified"


def test_researcher_down_shows_last_top_k_as_stale(orchestrated):
    config, env, _ = orchestrated
    env["RESEARCHER_URL"] = "http://127.0.0.1:9"
    report = orchestrator_run.run(config, env, sleep=lambda s: None).read_text()
    run, state = FakeBackend.saved
    assert run["stale"] and run["failed_workers"] == ["researcher"] and run["new_items"] == []
    assert "No new results" in report and "Old item (stale)" in report
    assert state["last_top_k"] == ["old"]


# ---------- the researcher's loop (tracker/research.py) ----------

from tracker import research as research_module
from tracker.errors import TransientServiceError

RESEARCH_CONFIG = {"instructions": "test", "allowed_hosts": ["example.com"], "relevance_terms": ["festival", "coachella"],
                   "model": {"name": "m"}, "limits": {"max_searches": 4, "max_retries": 0, "max_article_chars_for_model": 500}}
ARTICLE = {"url": "https://example.com/a", "title": "FireChat at Coachella", "text": PAGE, "bytes": 10}


def scripted(monkeypatch, turns):
    def fake_model(*args, **kwargs):
        turn = turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return {"role": "assistant", "content": ""}, turn, 100
    monkeypatch.setattr(research_module, "call_model", fake_model)
    monkeypatch.setattr(research_module, "fetch_article", lambda url, config, on_request=None: (on_request(), ARTICLE)[1])


def run_research(deadline_seconds=60, budget=None):
    return research_module.research(topic="festival", k=5, budget=budget or {"max_steps": 10, "max_fetches": 8, "max_tokens": 40000},
                                    deadline=time.monotonic() + deadline_seconds, config=RESEARCH_CONFIG, groq_key="g",
                                    tavily_key="t", trace=TraceLog("researcher"), ids={"run_id": "r", "request_id": "q"})


def finish_call(*claims):
    return [{"id": "f", "name": "finish", "args": {"developments": [{
        "title": "FireChat at Coachella", "summary": "Mesh chat at a festival.", "organization": "Open Garden",
        "technology": "mesh chat", "action": "pilot", "claims": list(claims)}]}}]


def test_research_returns_contract_developments(monkeypatch):
    scripted(monkeypatch, [[{"id": "1", "name": "fetch_article", "args": {"url": "https://example.com/a"}}],
                           finish_call({"text": "FireChat worked at Coachella.", "source_url": "https://example.com/a"},
                                       {"text": "It was invented.", "source_url": "https://example.com/never-fetched"})])
    outcome = run_research()
    validate_research_result({"developments": outcome["developments"]})
    assert outcome["status"] == "complete" and outcome["usage"] == {"steps": 2, "fetches": 1, "tokens": 200}
    assert [c["source_url"] for c in outcome["developments"][0]["claims"]] == ["https://example.com/a"]


def test_research_rate_limited_before_evidence_asks_for_a_retry(monkeypatch):
    scripted(monkeypatch, [TransientServiceError("tokens per minute")])
    with pytest.raises(research_module.ResearchRateLimited):
        run_research()


def test_research_with_no_time_left_is_partial(monkeypatch):
    scripted(monkeypatch, [])
    outcome = run_research(deadline_seconds=1)
    assert outcome["status"] == "partial" and outcome["error"][0] == "time_budget_exhausted" and outcome["developments"] == []


def test_research_fetch_budget_counts_requests(monkeypatch):
    scripted(monkeypatch, [[{"id": "1", "name": "fetch_article", "args": {"url": "https://example.com/a"}}],
                           [{"id": "2", "name": "fetch_article", "args": {"url": "https://example.com/b"}}],
                           finish_call({"text": "FireChat worked at Coachella.", "source_url": "https://example.com/a"})])
    outcome = run_research(budget={"max_steps": 10, "max_fetches": 1, "max_tokens": 40000})
    assert outcome["status"] == "partial" and outcome["usage"]["fetches"] == 1 and len(outcome["developments"]) == 1
