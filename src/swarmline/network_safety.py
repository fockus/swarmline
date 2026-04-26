"""Helpers for validating local hosts and remote HTTP targets."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})
_METADATA_HOSTS = frozenset(
    {"169.254.169.254", "metadata.google.internal", "100.100.100.200"}
)


def is_loopback_host(host: str) -> bool:
    """Return True if host is an explicit local-only bind target."""
    normalized = host.strip().lower()
    if normalized in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_http_endpoint_url(
    url: str,
    *,
    allow_private_network: bool = False,
    allow_insecure_http: bool = False,
) -> str | None:
    """Return rejection reason for an unsafe HTTP endpoint, else None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in {"http", "https"}:
        return f"Unsupported scheme: {parsed.scheme or '<missing>'}"
    if parsed.scheme == "http" and not allow_insecure_http:
        return "Insecure HTTP is disabled"

    hostname = parsed.hostname or ""
    if not hostname:
        return "Missing host"
    normalized = hostname.lower()

    if normalized in _METADATA_HOSTS:
        return f"Blocked host: {hostname}"

    if allow_private_network:
        return None

    if normalized in _LOCAL_HOSTS:
        return f"Blocked host: {hostname}"

    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        addr = None

    if addr is not None:
        if _is_non_public_ip(addr):
            return f"Private/reserved IP blocked: {hostname}"
        return None

    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
    except socket.gaierror:
        return None

    for _family, _socktype, _proto, _canonname, sockaddr in addrs:
        resolved = sockaddr[0]
        if not isinstance(resolved, str):
            continue
        try:
            resolved_ip = ipaddress.ip_address(resolved)
        except ValueError:
            continue
        if _is_non_public_ip(resolved_ip):
            return f"DNS resolves to private IP: {resolved}"

    return None


def _is_non_public_ip(addr: Any) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )
