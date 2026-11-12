"""These tests use no network, API keys, or credits."""
import json
from types import SimpleNamespace

import pytest

from tracker import model, retry, runtime, tools
from tracker.budgets import Budgets
from tracker.dedupe import is_placeholder, merge_developments
from tracker.errors import (
    ArticleUnavailable,
    BudgetExhausted,
    TerminalServiceError,
    TransientServiceError,
    UnsafeUrlError,
)
from tracker.policy import validate_public_url
from tracker.report import build_report

CONFIG = {
    "topic": "festival connectivity",
    "k": 5,
    "model": {"name": "test-model"},
    "instructions": "test",
    "allowed_hosts": ["example.com"],
    "allowed_schemes": ["https"],
    "relevance_terms": ["festival"],
    "limits": {
        "max_steps": 12, "max_searches": 4, "max_fetches": 3, "max_model_calls": 12,
        "max_total_tokens": 50000, "max_retries": 0, "request_timeout_seconds": 1,
        "max_article_bytes": 100000, "max_article_chars_for_model": 500,
    },
}
GOOD_EVIDENCE = "This mesh app helps friends find each other at a music festival."
ARTICLE = {"url": "https://example.com/a", "title": "Mesh app", "text": f"Intro. {GOOD_EVIDENCE} End.", "bytes": 10}


def development(url="https://example.com/a", evidence=GOOD_EVIDENCE, **extra):
    return {
        "title": "Mesh app launches", "summary": "s", "organization": "Acme", "technology": "Bluetooth mesh",
        "action": "launch", "date": "2026", "score": 5,
        "sources": [{"url": url, "title": "t", "evidence": evidence}], **extra,
    }


def call(name, **args):
    return {"id": f"{name}-id", "name": name, "args": args}


class FakeClient:
    state = {}
    saved = None

    def __init__(self, *args):
        pass

    def get_state(self):
        return dict(FakeClient.state)

    def get_runs(self):
        return []

    def save_run(self, run, state):
        FakeClient.saved = (run, state)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "load_settings", lambda: json.loads(json.dumps(CONFIG)))
    monkeypatch.setattr(runtime, "StateClient", FakeClient)
    for name in ("GROQ_API_KEY", "TAVILY_API_KEY", "TRACKER_USERNAME", "TRACKER_PASSWORD"):
        monkeypatch.setenv(name, "test")
    FakeClient.state = {}
    FakeClient.saved = None

    def script(*turns, tokens=100):
        queue = list(turns)

        def fake_model(*args, **kwargs):
            calls = queue.pop(0) if queue else [call("finish", developments=[])]
            return {"role": "assistant", "content": ""}, calls, tokens
        monkeypatch.setattr(runtime, "call_model", fake_model)
    return SimpleNamespace(script=script, root=tmp_path, monkeypatch=monkeypatch)


def trace_statuses(root, number=1):
    lines = (root / "traces" / f"run{number}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_blocked_article_does_not_end_the_run(harness):
    def fake_fetch(url, config):
        if url.endswith("blocked"):
            raise ArticleUnavailable("HTTP 403")
        return ARTICLE
    harness.monkeypatch.setattr(runtime, "fetch_article", fake_fetch)
    harness.script(
        [call("fetch_article", url="https://example.com/blocked")],
        [call("fetch_article", url="https://example.com/a")],
        [call("finish", developments=[development()])],
    )
    runtime.run_tracker()
    run, state = FakeClient.saved
    assert run["status"] == "complete"
    assert [item["status"] for item in run["articles"]] == ["failed", "fetched"]
    assert "https://example.com/blocked" not in state["seen_urls"]


def test_search_is_allowed_when_every_result_was_already_read(harness):
    """Run 4 spent its whole token budget stuck here."""
    FakeClient.state = {"seen_urls": ["https://example.com/old"], "developments": [], "last_top_k": []}
    searches = []

    def fake_search(query, key, config):
        searches.append(query)
        return {"query": query, "results": [{"title": "old", "url": "https://example.com/old", "snippet": ""}], "rejected": []}
    harness.monkeypatch.setattr(runtime, "search_web", fake_search)
    harness.script(*[[call("search_web", query=str(number))] for number in range(3)], [call("finish", developments=[])], [call("finish", developments=[])])
    runtime.run_tracker()
    assert len(searches) == 3
    assert not [event for event in trace_statuses(harness.root) if event["status"] == "blocked"]


def test_repeated_blocked_searches_stop_early(harness):
    harness.monkeypatch.setattr(
        runtime, "search_web",
        lambda query, key, config: {"query": query, "results": [{"title": "n", "url": f"https://example.com/{query}", "snippet": ""}], "rejected": []},
    )
    harness.script(*[[call("search_web", query=str(number))] for number in range(10)])
    runtime.run_tracker()
    run, _ = FakeClient.saved
    assert run["status"] == "partial"
    assert run["budget_usage"]["model_calls"] == 5
    assert "kept searching" in run["stop_reason"]


def test_budget_exhaustion_still_reports_fetched_evidence(harness):
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: {**ARTICLE, "url": url})
    harness.script(
        *[[call("fetch_article", url=f"https://example.com/{number}")] for number in range(4)],
        [call("finish", developments=[development(url="https://example.com/0")])],
    )
    runtime.run_tracker()
    run, _ = FakeClient.saved
    assert run["status"] == "partial"
    assert run["stop_reason"] == "max_fetches exhausted"
    assert len(run["new_items"]) == 1


def test_malformed_tool_call_is_returned_to_the_model(harness):
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: ARTICLE)
    harness.script(
        [{"id": "x", "name": "fetch_article", "args": {}}],
        [{"id": "y", "name": "made_up_tool", "args": {}}],
        [call("fetch_article", url="https://example.com/a")],
        [call("finish", developments=[development()])],
    )
    runtime.run_tracker()
    assert FakeClient.saved[0]["status"] == "complete"


def test_no_valid_development_is_reported_honestly(harness):
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: ARTICLE)
    bad = development(evidence="This sentence does not appear anywhere on the page at all.")
    harness.script(
        [call("fetch_article", url="https://example.com/a")],
        [call("finish", developments=[bad])],
        [call("finish", developments=[bad])],
    )
    report_path = runtime.run_tracker()
    run, state = FakeClient.saved
    assert run["status"] == "partial"
    assert run["new_items"] == [] and state["developments"] == []
    assert state["seen_urls"] == []  # the page can be read again next run
    assert "Fetched but not analyzed" in report_path.read_text()


def test_old_placeholder_entries_are_removed_and_their_pages_reopened(harness):
    placeholder = {
        "key": "needs-review-needs-review-fetched-article", "title": "findme", "organization": "Needs review",
        "technology": "Needs review", "action": "Fetched article", "score": 1,
        "sources": [{"url": "https://example.com/a", "title": "t", "evidence": "e"}],
    }
    FakeClient.state = {"seen_urls": ["https://example.com/a"], "developments": [placeholder], "last_top_k": [placeholder["key"]]}
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: ARTICLE)
    harness.script(
        [call("fetch_article", url="https://example.com/a")],
        [call("finish", developments=[development()])],
    )
    runtime.run_tracker()
    run, state = FakeClient.saved
    assert [item["organization"] for item in state["developments"]] == ["Acme"]
    assert run["dropped_items"] == [] and len(run["new_items"]) == 1


def test_second_run_labels_and_skips(harness):
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: ARTICLE)
    harness.script(
        [call("fetch_article", url="https://example.com/a")],
        [call("finish", developments=[development()])],
    )
    runtime.run_tracker()
    _, FakeClient.state = FakeClient.saved
    harness.script(
        [call("fetch_article", url="https://example.com/a?utm_source=x")],
        [call("finish", developments=[])],
        [call("finish", developments=[])],
    )
    report_path = runtime.run_tracker()
    assert report_path.name == "run2.md"
    run, _ = FakeClient.saved
    assert run["articles"][0]["status"] == "skipped"
    assert len(run["still_items"]) == 1 and run["new_items"] == []


def test_run_numbers_never_overwrite_existing_reports(harness):
    (harness.root / "reports").mkdir()
    (harness.root / "reports" / "run7.md").write_text("keep me")
    harness.script([call("finish", developments=[])], [call("finish", developments=[])])
    assert runtime.run_tracker().name == "run8.md"
    assert (harness.root / "reports" / "run7.md").read_text() == "keep me"


def test_trace_records_real_search_credits_and_tokens(harness):
    harness.monkeypatch.setattr(runtime, "search_web", lambda query, key, config: {"query": query, "results": [], "rejected": []})
    harness.script([call("search_web", query="q")], [call("finish", developments=[])], [call("finish", developments=[])])
    runtime.run_tracker()
    events = trace_statuses(harness.root)
    assert [event["tokens_or_credits"] for event in events if event["name"] == "search_web"] == [2]


def test_tokens_are_counted_and_the_final_reply_is_kept():
    budgets = Budgets(CONFIG["limits"])
    budgets.record_tokens(60000)
    assert budgets.usage["total_tokens"] == 60000
    with pytest.raises(BudgetExhausted):
        budgets.check_tokens()


def test_evidence_accepts_ellipses_and_typography_but_not_invention():
    page = "When the network dies at the festival, findme still finds your people. Built for crowds and dead-zones."
    assert runtime.evidence_is_verbatim("When the network dies at the festival, findme still finds your people… Built for crowds and dead‑zones", page)
    assert not runtime.evidence_is_verbatim("When the network dies at the festival… it also makes coffee for everyone", page)
    assert not runtime.evidence_is_verbatim("the", page)


def test_relevance_requires_a_festival_connection():
    fetched = {"https://example.com/a": {"url": "https://example.com/a", "title": "Puerto Rico", "text": "A mesh network helped connect Puerto Rico after the storm."}}
    item = development(evidence="A mesh network helped connect Puerto Rico after the storm.")
    assert runtime.validate_developments([item], fetched, ["festival"]) == []
    assert not runtime.is_relevant("a brave new phone", "x", ["rave"])


def test_different_wording_of_one_development_is_merged():
    old = development(key="old-key", title="findme offline friend finder")
    new = development(title="findme launches for festivals", technology="Bluetooth mesh", action="a different action sentence")
    new["sources"] = [{"url": "https://example.com/b", "title": "b", "evidence": "e"}]
    merged = merge_developments([old], [new])
    assert len(merged) == 1 and merged[0]["key"] == "old-key"
    assert len(merged[0]["sources"]) == 2


def test_placeholder_values_never_merge_unrelated_articles():
    first = development(title="Puerto Rico story", organization="Needs review", technology="Needs review")
    second = development(title="Totally unrelated app", organization="Needs review", technology="Needs review", action="other")
    assert is_placeholder(first)
    assert len(merge_developments([], [first, second])) == 2


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}
        self.text = body.decode("utf-8", "replace")
        self.ok = status < 400
        self.is_redirect = status in {301, 302, 303, 307, 308}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass

    def iter_content(self, size):
        yield self.body


@pytest.mark.parametrize("message", [
    "Rate limit reached for model on tokens per day (TPD): Limit 200000, Used 199000",
    "Rate limit reached for model on requests per day (RPD): Limit 1000",
])
def test_groq_daily_limit_wording_is_terminal(message):
    with pytest.raises(TerminalServiceError):
        retry.classify_response(FakeResponse(429, message.encode()))


def test_per_minute_limit_with_billing_link_is_transient():
    body = b"tokens per minute (TPM). Upgrade at https://console.groq.com/settings/billing"
    with pytest.raises(TransientServiceError):
        retry.classify_response(FakeResponse(429, body))


@pytest.mark.parametrize(("text", "header", "low", "high"), [
    ("Please try again in 389.999999ms.", None, 0.4, 1),
    ("Please try again in 1m2.5s.", None, 62, 63.5),
    ("", "7", 7, 8),
    ("no hint", None, 2, 2),
    ("Please try again in 3h", None, 65, 65),
])
def test_retry_wait(text, header, low, high):
    assert low <= retry.retry_wait(1, text, header) <= high


def test_utf8_page_without_charset_is_not_garbled(monkeypatch):
    monkeypatch.setattr(tools, "validate_public_url", lambda url, config, **kwargs: url)
    html = "<html><head><title>findme · app</title></head><body><main>Find your crew · offline</main></body></html>".encode()
    monkeypatch.setattr(tools.requests, "get", lambda *args, **kwargs: FakeResponse(200, html, {"Content-Type": "text/html"}))
    result = tools.fetch_article("https://example.com/a", CONFIG)
    assert result["title"] == "findme · app" and "crew · offline" in result["text"]


@pytest.mark.parametrize(("response", "reason"), [
    (FakeResponse(403), "403"),
    (FakeResponse(404), "404"),
    (FakeResponse(503), "503"),
    (FakeResponse(200, b"x", {"Content-Type": "application/pdf"}), "content type"),
    (FakeResponse(200, b"x" * 200000, {"Content-Type": "text/html"}), "size limit"),
])
def test_unreadable_pages_raise_article_unavailable(monkeypatch, response, reason):
    monkeypatch.setattr(tools, "validate_public_url", lambda url, config, **kwargs: url)
    monkeypatch.setattr(tools.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(ArticleUnavailable, match=reason):
        tools.fetch_article("https://example.com/a", CONFIG)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"])
def test_allowlisted_host_resolving_to_private_address_is_rejected(monkeypatch, address):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, "", (address, 443))])
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("https://example.com/a", CONFIG)


def test_redirect_to_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))])
    redirect = FakeResponse(302, b"", {"Location": "https://internal.test/admin"})
    monkeypatch.setattr(tools.requests, "get", lambda *args, **kwargs: redirect)
    with pytest.raises(UnsafeUrlError):
        tools.fetch_article("https://example.com/a", CONFIG)


def test_report_has_required_sections_in_order():
    report = build_report("t", "complete", [development()], [], [], {}, None)
    assert report.index("## New") < report.index("## Still tracking") < report.index("## Dropped from the Top K")
    assert "https://example.com/a" in report


class FakeGroqError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers={})


def fake_groq(monkeypatch, outcomes):
    attempts = []

    def create(**kwargs):
        attempts.append(kwargs)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(model, "Groq", lambda **kwargs: client)
    monkeypatch.setattr(model.time, "sleep", lambda seconds: None)
    return attempts


def model_reply():
    function = SimpleNamespace(name="finish", arguments='{"developments": []}')
    message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="1", function=function)])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=9))


def test_per_minute_model_limit_is_retried(monkeypatch):
    error = FakeGroqError("tokens per minute (TPM). Please try again in 390ms. Upgrade at .../settings/billing", 429)
    attempts = fake_groq(monkeypatch, [error, model_reply()])
    _, calls, tokens = model.call_model("key", "m", [], max_retries=2)
    assert len(attempts) == 2 and calls[0]["name"] == "finish" and tokens == 9


def test_daily_model_limit_is_not_retried(monkeypatch):
    error = FakeGroqError("Rate limit reached on tokens per day (TPD): Limit 200000", 429)
    attempts = fake_groq(monkeypatch, [error, model_reply()])
    with pytest.raises(TerminalServiceError):
        model.call_model("key", "m", [], max_retries=2)
    assert len(attempts) == 1


def test_retries_stop_at_the_cap(monkeypatch):
    errors = [FakeGroqError("tokens per minute (TPM)", 429) for _ in range(5)]
    attempts = fake_groq(monkeypatch, errors)
    with pytest.raises(TransientServiceError):
        model.call_model("key", "m", [], max_retries=2)
    assert len(attempts) == 3


def test_runtime_requires_fetch_then_finish_when_needed(harness):
    """Run 5 kept asking to search and then repeated rejected work."""
    required = []
    turns = [
        [call("search_web", query="1")],
        [call("search_web", query="2")],
        [call("fetch_article", url="https://example.com/1")],
        [call("finish", developments=[development(url="https://example.com/1", evidence="This sentence does not appear anywhere on that page.")])],
        [call("finish", developments=[development(url="https://example.com/1")])],
    ]

    def fake_model(*args, **kwargs):
        required.append(kwargs["required_tool"])
        return {"role": "assistant", "content": ""}, turns.pop(0), 100
    harness.monkeypatch.setattr(runtime, "call_model", fake_model)
    harness.monkeypatch.setattr(
        runtime, "search_web",
        lambda query, key, config: {"query": query, "results": [{"title": "n", "url": "https://example.com/1", "snippet": ""}], "rejected": []},
    )
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: {**ARTICLE, "url": url})
    runtime.run_tracker()
    assert required == [None, None, "fetch_article", None, "finish"]
    assert FakeClient.saved[0]["status"] == "complete"
    rejected = [event for event in trace_statuses(harness.root) if event["status"] == "rejected"]
    assert "Not found word for word" in rejected[0]["detail"]


def test_large_context_goes_straight_to_finish(harness):
    required = []
    turns = [[call("fetch_article", url="https://example.com/a")], [call("finish", developments=[development()])]]

    def fake_model(*args, **kwargs):
        required.append(kwargs["required_tool"])
        return {"role": "assistant", "content": ""}, turns.pop(0), 7000
    settings = json.loads(json.dumps(CONFIG))
    settings["limits"]["max_context_tokens"] = 6000
    harness.monkeypatch.setattr(runtime, "load_settings", lambda: settings)
    harness.monkeypatch.setattr(runtime, "call_model", fake_model)
    harness.monkeypatch.setattr(runtime, "fetch_article", lambda url, config: ARTICLE)
    runtime.run_tracker()
    assert required == [None, "finish"]


def test_calls_wait_for_the_per_minute_window(monkeypatch):
    clock = {"now": 100.0}
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock["now"] += seconds
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(runtime.time, "sleep", sleep)
    history = [(90.0, 5000)]
    runtime.wait_for_token_window(history, 4000, 7500)
    assert waits == [50.0] and history == []
    runtime.wait_for_token_window([(99.0, 1000)], 1000, 7500)
    assert len(waits) == 1


def test_ignored_forced_tool_falls_back_to_any_tool(monkeypatch):
    """Orchestrated run 4: Groq returned 400 when the model called search_web while fetch_article was forced."""
    error = FakeGroqError("Tool call validation failed: attempted to call tool 'search_web' which does not match request.tool_choice", 400)
    attempts = fake_groq(monkeypatch, [error, model_reply()])
    model.call_model("key", "m", [], required_tool="fetch_article", max_retries=2, max_completion_tokens=900, reasoning_effort="low")
    assert attempts[1]["tool_choice"] == "required"
    assert attempts[0]["max_completion_tokens"] == 900 and attempts[0]["extra_body"] == {"reasoning_effort": "low"}
