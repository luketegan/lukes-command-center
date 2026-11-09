import re
import time

import requests

from .errors import TerminalServiceError, TransientServiceError

DAILY_LIMIT_MARKERS = (
    "per day", "(tpd)", "(rpd)", "daily quota", "daily limit",
    "quota exceeded", "insufficient_quota",
)
MAX_RETRY_WAIT_SECONDS = 65.0


def is_daily_limit(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in DAILY_LIMIT_MARKERS)


def classify_response(response: requests.Response) -> None:
    if response.ok:
        return
    text = response.text[:1000]
    status = response.status_code
    if status in {401, 402, 403}:
        raise TerminalServiceError(f"terminal HTTP {status}: {text[:200]}")
    if status == 429:
        if is_daily_limit(text):
            raise TerminalServiceError(f"daily limit HTTP 429: {text[:200]}")
        raise TransientServiceError(f"transient HTTP 429: {text[:200]}")
    if status >= 500:
        raise TransientServiceError(f"transient HTTP {status}: {text[:200]}")
    raise TerminalServiceError(f"HTTP {status}: {text[:200]}")


def retry_wait(attempt: int, text: str = "", retry_after: str | None = None) -> float:
    """Use the wait the service asked for, otherwise capped exponential backoff."""
    hinted = None
    if retry_after:
        try:
            hinted = float(retry_after)
        except ValueError:
            hinted = None
    if hinted is None:
        match = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)(ms|s))?", text, re.IGNORECASE)
        if match and any(match.group(index) for index in (1, 2, 3)):
            hinted = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
            if match.group(3):
                hinted += float(match.group(3)) / (1000 if match.group(4).lower() == "ms" else 1)
    if hinted is None:
        return float(min(2 ** attempt, 8))
    return min(hinted + 0.25, MAX_RETRY_WAIT_SECONDS)


def with_retries(operation, max_retries: int):
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except (requests.Timeout, requests.ConnectionError, TransientServiceError) as exc:
            if attempt >= max_retries:
                raise TransientServiceError(f"retry limit reached: {exc}") from exc
            time.sleep(retry_wait(attempt, str(exc)))
