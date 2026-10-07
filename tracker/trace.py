import json
import time
from pathlib import Path


class TraceWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def record(self, *, step: int, kind: str, name: str, args: dict,
               status: str, started: float, tokens: int = 0,
               detail: str | None = None) -> None:
        safe_args = {k: v for k, v in args.items() if "key" not in k.lower() and "password" not in k.lower()}
        event = {
            "timestamp": time.time(), "step": step, "kind": kind,
            "name": name, "args": safe_args, "status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "tokens_or_credits": tokens,
        }
        if detail:
            event["detail"] = detail[:500]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

