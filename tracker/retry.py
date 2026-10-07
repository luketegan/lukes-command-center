import time

import requests

from .errors import TerminalServiceError, TransientServiceError


def classify_response(response: requests.Response) -> None:
    if response.ok:
        return
    text = response.text.lower()[:1000]
    if response.status_code in {401, 402, 403} or any(word in text for word in ("billing", "payment", "daily quota", "invalid api key")):
        raise TerminalServiceError(f"terminal HTTP {response.status_code}: {text[:200]}")
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientServiceError(f"transient HTTP {response.status_code}: {text[:200]}")
    raise TerminalServiceError(f"HTTP {response.status_code}: {text[:200]}")


def with_retries(operation, max_retries: int):
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except (requests.Timeout, requests.ConnectionError, TransientServiceError) as exc:
            if attempt >= max_retries:
                raise TransientServiceError(f"retry limit reached: {exc}") from exc
            time.sleep(min(2 ** attempt, 8))

