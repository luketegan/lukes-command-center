"""JSON-lines trace log with the fields every service must write."""
import json
import sys
import threading
import time
from pathlib import Path

FIELDS = ("ts", "service", "run_id", "request_id", "step", "direction",
          "endpoint_or_tool", "status", "latency_ms", "attempt", "tokens")


class TraceLog:
    """Writes one JSON object per line. Never pass tokens, keys or request bodies to it."""

    def __init__(self, service: str, folder: Path | None = None, echo: bool = False, keep: int = 5000):
        self.service = service
        self.folder = folder
        self.echo = echo
        self.keep = keep
        self.lock = threading.Lock()
        self.memory: list[dict] = []

    def write(self, *, run_id, request_id, step, direction, endpoint_or_tool, status,
              latency_ms=None, attempt=1, tokens=0, **extra) -> dict:
        event = {
            "ts": round(time.time(), 3),
            "service": self.service,
            "run_id": run_id,
            "request_id": request_id,
            "step": step,
            "direction": direction,
            "endpoint_or_tool": endpoint_or_tool,
            "status": status,
            "latency_ms": None if latency_ms is None else round(latency_ms, 1),
            "attempt": attempt,
            "tokens": int(tokens or 0),
        }
        for key, value in extra.items():
            if key not in FIELDS and value is not None:
                event[key] = str(value)[:600]
        line = json.dumps(event, ensure_ascii=False)
        with self.lock:
            self.memory.append(event)
            del self.memory[:-self.keep]
            if self.folder and run_id:
                self.folder.mkdir(parents=True, exist_ok=True)
                with (self.folder / f"{run_id}.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            if self.echo:
                print(line, file=sys.stdout, flush=True)
        return event

    def for_run(self, run_id: str) -> list[dict]:
        with self.lock:
            return [event for event in self.memory if event["run_id"] == run_id]
