import ipaddress
import socket
from urllib.parse import urlparse

from .errors import UnsafeUrlError


def host_is_allowed(host: str, allowed_hosts: list[str]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(normalized == item.lower() or normalized.endswith("." + item.lower()) for item in allowed_hosts)


def validate_public_url(url: str, config: dict, *, resolve_dns: bool = True) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in config["allowed_schemes"]:
        raise UnsafeUrlError("URL scheme is not allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("URL host is invalid")
    if not host_is_allowed(parsed.hostname, config["allowed_hosts"]):
        raise UnsafeUrlError("URL host is not on the allowlist")
    if parsed.port not in (None, 443):
        raise UnsafeUrlError("Only the standard HTTPS port is allowed")
    if resolve_dns:
        try:
            addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeUrlError("URL host could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise UnsafeUrlError("URL resolves to a non-public address")
    return url

