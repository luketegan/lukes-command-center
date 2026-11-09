"""Researcher service: the A2 tracker behind POST /research."""
import os
from pathlib import Path

import yaml

from shared.contract import make_error, make_response, validate_research_payload
from shared.tracelog import TraceLog
from shared.worker_http import IdempotencyStore, RetryLater, make_handler, serve

ROOT = Path(__file__).resolve().parents[2]


def build_handler(trace: TraceLog | None = None, research_fn=None, config: dict | None = None):
    token = os.environ.get("RESEARCHER_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("RESEARCHER_TOKEN must be set to a long random value")
    if research_fn is None:
        from tracker.research import ResearchRateLimited, research
        research_fn = research
    else:
        from tracker.research import ResearchRateLimited
    config = config or yaml.safe_load((ROOT / "tracker" / "config.yaml").read_text(encoding="utf-8"))
    trace = trace or TraceLog("researcher", ROOT / "traces" / "researcher")

    def work(envelope, deadline, trace_log):
        payload = envelope["payload"]
        try:
            outcome = research_fn(
                topic=payload["topic"], k=payload["k"], budget=envelope["budget"], deadline=deadline,
                config=config, groq_key=os.environ.get("GROQ_API_KEY", ""),
                tavily_key=os.environ.get("TAVILY_API_KEY", ""), trace=trace_log,
                ids={"run_id": envelope["run_id"], "request_id": envelope["request_id"]})
        except ResearchRateLimited as exc:
            raise RetryLater(str(exc)[:300], 30) from exc
        error = make_error(outcome["error"][0], outcome["error"][1], False) if outcome["error"] else None
        if outcome["status"] == "failed":
            return 500, make_response(envelope, "failed", outcome["usage"], None, error)
        return 200, make_response(envelope, outcome["status"], outcome["usage"],
                                  {"developments": outcome["developments"]}, error)

    return make_handler(service="researcher", token=token, trace=trace, store=IdempotencyStore(),
                        routes={"/research": (validate_research_payload, work)})


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "tracker" / ".env")
    for name in ("GROQ_API_KEY", "TAVILY_API_KEY"):
        if not os.environ.get(name):
            raise SystemExit(f"{name} is missing from tracker/.env")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("RESEARCHER_PORT", "8101"))
    server = serve(build_handler(), host, port)
    print(f"researcher listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
