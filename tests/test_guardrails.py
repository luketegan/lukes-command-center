import pytest

from tracker.errors import UnsafeUrlError
from tracker.policy import validate_public_url


CONFIG = {"allowed_schemes": ["https"], "allowed_hosts": ["example.com"]}


@pytest.mark.parametrize("url", [
    "http://example.com/article",
    "file:///etc/passwd",
    "https://localhost/article",
    "https://127.0.0.1/article",
    "https://evil.example.net/article",
    "https://user:pass@example.com/article",
    "https://example.com:8443/article",
])
def test_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url, CONFIG, resolve_dns=False)


def test_accepts_allowlisted_https_url_without_dns_lookup():
    assert validate_public_url("https://news.example.com/article", CONFIG, resolve_dns=False)

