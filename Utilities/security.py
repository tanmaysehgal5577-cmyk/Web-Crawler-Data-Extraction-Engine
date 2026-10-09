"""
Utilities/security.py
SSRF guard and safe DNS resolver for CrawlMind.

Defenses:
  - Scheme whitelist (http/https only)
  - Userinfo (@) in URL rejection
  - Private/loopback/link-local/multicast IP rejection (IPv4 + IPv6)
  - Metadata-service IP rejection (169.254.169.254)
  - SafeResolver: validates resolved IPs AFTER DNS resolution (DNS-rebinding defence)
  - All blocked attempts are logged as audit events
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

from Utilities.constants import ALLOWED_SCHEMES, PRIVATE_IPV4_RANGES
from Utilities.exceptions import SecurityValidationError

logger = logging.getLogger(__name__)

# Regex to detect userinfo in URLs (user:pass@host or user@host)
_USERINFO_RE = re.compile(r"://[^/]*@")


def _is_private_ipv4(addr: ipaddress.IPv4Address) -> bool:
    """Return True if IPv4 address is in any private/special range."""
    ip_int = int(addr)
    for (network, mask) in PRIVATE_IPV4_RANGES:
        if (ip_int & mask) == (network & mask):
            return True
    return False


def _is_private_ipv6(addr: ipaddress.IPv6Address) -> bool:
    """Return True if IPv6 address is loopback, link-local, private, or special."""
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_private
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        # IPv4-mapped: ::ffff:127.0.0.1 etc.
        or (addr.ipv4_mapped is not None and _is_private_ipv4(addr.ipv4_mapped))
    )


def validate_ip(ip_str: str, url: str = "") -> None:
    """
    Raise SecurityValidationError if *ip_str* resolves to a private/internal address.

    Args:
        ip_str: IP address string (IPv4 or IPv6).
        url:    Original URL (for error messages and audit logging).
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        raise SecurityValidationError(
            f"Cannot parse resolved IP: {ip_str!r}", url=url, reason="invalid_ip"
        )

    if isinstance(addr, ipaddress.IPv4Address):
        if _is_private_ipv4(addr):
            logger.warning(
                "SSRF block: private IPv4",
                extra={"url": url, "error_type": "ssrf_private_ipv4"},
            )
            raise SecurityValidationError(
                f"Resolved IP {ip_str} is private/internal (SSRF protection)",
                url=url,
                reason="ssrf_private_ipv4",
            )
    elif isinstance(addr, ipaddress.IPv6Address):
        if _is_private_ipv6(addr):
            logger.warning(
                "SSRF block: private IPv6",
                extra={"url": url, "error_type": "ssrf_private_ipv6"},
            )
            raise SecurityValidationError(
                f"Resolved IP {ip_str} is private/internal (SSRF protection)",
                url=url,
                reason="ssrf_private_ipv6",
            )


def validate_url_security(url: str, block_private_networks: bool = True) -> None:
    """
    Validate *url* against security policy BEFORE making any network request.

    Checks performed (in order):
      1. Non-empty URL
      2. Scheme must be http or https
      3. Userinfo (@) must be absent
      4. Hostname must be present
      5. If IP literal — validate immediately (no DNS needed)
      6. Port range (1–65535 if specified)

    DNS-resolved IP validation is done separately by SafeResolver inside aiohttp.

    Args:
        url:                    URL to validate.
        block_private_networks: If False, skip IP range checks (for tests only).

    Raises:
        SecurityValidationError: On any policy violation.
    """
    if not url:
        raise SecurityValidationError("Empty URL", url=url, reason="empty_url")

    # Scheme check
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SecurityValidationError(
            f"Scheme {parsed.scheme!r} is not allowed (only http/https)",
            url=url,
            reason="disallowed_scheme",
        )

    # Userinfo check — catches user@host, user:pass@host
    if _USERINFO_RE.search(url):
        raise SecurityValidationError(
            "URL contains userinfo (@ in authority) which is not allowed",
            url=url,
            reason="userinfo_in_url",
        )

    hostname = parsed.hostname
    if not hostname:
        raise SecurityValidationError(
            "URL has no hostname", url=url, reason="no_hostname"
        )

    # Port range
    port = parsed.port
    if port is not None and not (1 <= port <= 65535):
        raise SecurityValidationError(
            f"Port {port} is out of valid range (1–65535)",
            url=url,
            reason="invalid_port",
        )

    if not block_private_networks:
        return

    # If hostname is already an IP literal, validate immediately
    try:
        addr = ipaddress.ip_address(hostname)
        validate_ip(str(addr), url=url)
    except ValueError:
        # Not an IP literal; SafeResolver will validate after DNS resolution
        pass


class SafeResolver:
    """
    Async DNS resolver wrapper that validates every resolved IP after lookup.

    Instantiate and pass as ``connector=aiohttp.TCPConnector(resolver=SafeResolver())``
    when building the aiohttp ClientSession.

    This defends against DNS-rebinding attacks: even if an attacker controls
    DNS and makes a public hostname resolve to 127.0.0.1, we block it.
    """

    def __init__(self, block_private_networks: bool = True) -> None:
        self._block = block_private_networks

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> list[dict[str, Any]]:
        """
        Resolve *host* using getaddrinfo, then validate every IP.

        Raises:
            SecurityValidationError: If any resolved address is private/internal.
        """
        loop_results: list[tuple[Any, ...]] = await _async_getaddrinfo(host, port, family)
        records: list[dict[str, Any]] = []
        for af, socktype, proto, canonname, sockaddr in loop_results:
            ip = sockaddr[0]
            if self._block:
                validate_ip(ip, url=f"resolved://{host}")
            records.append(
                {
                    "hostname": host,
                    "host": ip,
                    "port": sockaddr[1],
                    "family": af,
                    "proto": proto,
                    "flags": 0,
                }
            )
        if not records:
            raise SecurityValidationError(
                f"DNS resolution returned no addresses for {host!r}",
                url=f"resolved://{host}",
                reason="no_dns_result",
            )
        return records


async def _async_getaddrinfo(
    host: str,
    port: int,
    family: socket.AddressFamily,
) -> list[tuple[Any, ...]]:
    """Run blocking getaddrinfo in the default executor."""
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(  # type: ignore[return-value]
        None,
        lambda: socket.getaddrinfo(
            host,
            port,
            family=family,
            type=socket.SOCK_STREAM,
        ),
    )
