import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(kept), ""))


def development_key(item: dict) -> str:
    value = " ".join(str(item.get(key, "")) for key in ("organization", "technology", "action"))
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:180]


def merge_developments(previous: list[dict], candidates: list[dict]) -> list[dict]:
    merged = {item.get("key") or development_key(item): item for item in previous}
    for item in candidates:
        item = dict(item)
        item["key"] = development_key(item)
        old = merged.get(item["key"])
        if old:
            urls = {source.get("url") for source in old.get("sources", [])}
            item["sources"] = old.get("sources", []) + [source for source in item.get("sources", []) if source.get("url") not in urls]
        merged[item["key"]] = item
    return sorted(merged.values(), key=lambda row: float(row.get("score", 0)), reverse=True)

