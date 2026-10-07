import argparse
import json
import os
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from .errors import UnsafeUrlError
from .policy import validate_public_url
from .retry import classify_response, with_retries


def search_web(query: str, api_key: str, config: dict) -> dict:
    def operation():
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "search_depth": "advanced", "max_results": 8},
            timeout=config["limits"]["request_timeout_seconds"],
        )
        classify_response(response)
        return response.json()
    raw = with_retries(operation, config["limits"]["max_retries"])
    results = []
    rejected = []
    for item in raw.get("results", []):
        try:
            validate_public_url(item.get("url", ""), config)
        except UnsafeUrlError as exc:
            rejected.append({
                "title": item.get("title", "Rejected search result"),
                "url": item.get("url", ""),
                "status": "rejected",
                "reason": str(exc),
            })
            continue
        results.append({
            "title": item.get("title", ""), "url": item.get("url", ""),
            "snippet": item.get("content", "")[:1200],
        })
    return {"query": query, "results": results, "rejected": rejected}


def fetch_article(url: str, config: dict) -> dict:
    current = validate_public_url(url, config)
    timeout = config["limits"]["request_timeout_seconds"]
    max_bytes = config["limits"]["max_article_bytes"]
    for _ in range(4):
        def operation():
            return requests.get(
                current, timeout=timeout, stream=True, allow_redirects=False,
                headers={"User-Agent": "FestivalConnectivityTracker/1.0"},
            )
        response = with_retries(operation, config["limits"]["max_retries"])
        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                raise ValueError("Redirect did not include a location")
            current = validate_public_url(urljoin(current, location), config)
            continue
        classify_response(response)
        content_type = response.headers.get("Content-Type", "").lower()
        if not any(item in content_type for item in ("text/html", "text/plain", "application/xhtml+xml")):
            raise ValueError(f"Unsupported content type: {content_type}")
        chunks, total = [], 0
        for chunk in response.iter_content(16384):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Article exceeds the configured size limit")
            chunks.append(chunk)
        html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        title = unescape(soup.title.get_text(" ", strip=True)) if soup.title else current
        for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        return {"url": current, "title": title[:300], "text": text[:60000], "bytes": total}
    raise ValueError("Too many redirects")


def finish(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("developments"), list):
        raise ValueError("finish requires an object containing a developments list")
    return report


def load_config(path: str = "tracker/config.yaml") -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description="Call tracker tools without the model")
    parser.add_argument("tool", choices=["search_web", "fetch_article", "finish"])
    parser.add_argument("value", help="query, URL, or JSON object")
    parser.add_argument("--config", default="tracker/config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.tool == "search_web":
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise SystemExit("TAVILY_API_KEY is missing from tracker/.env")
        result = search_web(args.value, api_key, config)
    elif args.tool == "fetch_article":
        result = fetch_article(args.value, config)
    else:
        result = finish(json.loads(args.value))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
