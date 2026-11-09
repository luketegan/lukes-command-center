import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLACEHOLDER_VALUES = {"", "needs review", "unknown", "n/a", "none"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(kept), ""))


def _slug(value) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def development_key(item: dict) -> str:
    value = " ".join(str(item.get(key, "")) for key in ("organization", "technology", "action"))
    return _slug(value)[:180]


def is_placeholder(item: dict) -> bool:
    """Older runs saved raw pages with no real organization or technology."""
    return (
        str(item.get("organization", "")).strip().lower() in PLACEHOLDER_VALUES
        and str(item.get("technology", "")).strip().lower() in PLACEHOLDER_VALUES
    )


def _similar(left, right) -> float:
    return SequenceMatcher(None, _slug(left), _slug(right)).ratio()


def is_same_development(left: dict, right: dict) -> bool:
    """Treat differently worded write-ups of one development as the same item."""
    if _slug(left.get("title")) and _similar(left.get("title"), right.get("title")) >= 0.85:
        return True
    left_org, right_org = _slug(left.get("organization")), _slug(right.get("organization"))
    if not left_org or left_org != right_org or left_org in {_slug(v) for v in PLACEHOLDER_VALUES}:
        return False
    return _similar(left.get("technology"), right.get("technology")) >= 0.7


def _score(item: dict) -> float:
    try:
        return float(item.get("score", 0))
    except (TypeError, ValueError):
        return 0.0


def merge_developments(previous: list[dict], candidates: list[dict]) -> list[dict]:
    merged = {item.get("key") or development_key(item): item for item in previous}
    for item in candidates:
        item = dict(item)
        item["key"] = development_key(item)
        if item["key"] not in merged:
            match = next((key for key, old in merged.items() if is_same_development(item, old)), None)
            if match:
                item["key"] = match
        old = merged.get(item["key"])
        if old:
            urls = {source.get("url") for source in old.get("sources", [])}
            item["sources"] = old.get("sources", []) + [source for source in item.get("sources", []) if source.get("url") not in urls]
        merged[item["key"]] = item
    return sorted(merged.values(), key=_score, reverse=True)
