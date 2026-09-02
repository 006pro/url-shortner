import hashlib
import ipaddress
import secrets
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


def generate_api_key() -> str:
    return f"usk_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class UnsafeUrlError(ValueError):
    """Raised when a target URL fails validation (bad scheme, private/loopback
    host, unresolvable host, etc.). Message is safe to show to the caller."""


def _is_blocked_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    """Validate that `url` points at a public HTTP(S) host, to prevent the
    service being used as an SSRF proxy against localhost / internal networks.

    This resolves the hostname at creation time. It does not protect against
    DNS rebinding (a hostname that resolves safely now but to a private IP
    later, at redirect time) -- see README "Security" section.
    """
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme must be one of {sorted(ALLOWED_SCHEMES)}")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeUrlError("URL must include a host")

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeUrlError("URLs pointing at localhost are not allowed")

    # If the host is already a literal IP, this succeeds without a DNS lookup.
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {hostname}") from exc

    resolved_ips = {info[4][0] for info in addrinfo}
    if not resolved_ips:
        raise UnsafeUrlError(f"Could not resolve host: {hostname}")

    for ip_str in resolved_ips:
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError("URL resolves to a private, loopback, or reserved IP address")

    return url
