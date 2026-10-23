"""URL, hostname, and IP address vetting (research R12).

These checks are purely syntactic or work on already-resolved addresses; they never touch the
network, so they can also be used to validate untrusted URLs before storing them.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from netc.fetch.errors import UnsafeURLError

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")
_LABEL = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")
# Real top-level domains are alphabetic or punycode; this also rules out numeric IP forms
# such as "127.1", "0x7f.0.0.1", and "2130706433".
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")


def is_public_ip(ip: IPAddress) -> bool:
    """True only for globally routable unicast addresses."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip in _NAT64:
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF))
        if ip in _IPV4_COMPATIBLE:
            return False
    return ip.is_global and not ip.is_multicast


def vet_hostname(host: str) -> str:
    """Return the normalized ASCII hostname, or raise UnsafeURLError."""
    host = host.strip().lower().rstrip(".")
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeURLError(f"IP address hosts are not allowed: {host}")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeURLError(f"Invalid international hostname: {host!r}") from exc
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2:
        raise UnsafeURLError(f"Hostname must be a fully qualified public name: {host}")
    if labels[-1] == "localhost":
        raise UnsafeURLError(f"localhost is not allowed: {host}")
    if not all(_LABEL.match(label) for label in labels) or not _TLD.match(labels[-1]):
        raise UnsafeURLError(f"Invalid hostname: {host}")
    return host


def vet_url(url: str, *, upgrade_http: bool = True) -> str:
    """Return a normalized ``https://`` URL on port 443, or raise UnsafeURLError.

    ``http://`` URLs are upgraded to ``https://`` when ``upgrade_http`` is true. User info,
    non-default ports, IP-literal hosts, and localhost are rejected. The fragment is dropped.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError(f"Malformed URL: {url!r}") from exc

    scheme = parts.scheme.lower()
    if scheme == "http" and upgrade_http:
        if port not in (None, 80):
            raise UnsafeURLError(f"Only the default port is allowed: {url!r}")
    elif scheme != "https":
        raise UnsafeURLError(f"Only https URLs are allowed: {url!r}")
    elif port not in (None, 443):
        raise UnsafeURLError(f"Only port 443 is allowed: {url!r}")

    if "@" in parts.netloc:
        raise UnsafeURLError("URLs with user info are not allowed")

    host = vet_hostname(parts.hostname or "")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def join_url(base: str, href: str) -> str:
    """``urljoin`` for addresses found in other sites' pages: a malformed one (like
    ``http://[x``, which makes urllib raise) becomes "" instead, which every check after this
    rejects. One such link stopped a whole discovery run (Oct 23, 2026)."""
    try:
        return urljoin(base, href)
    except ValueError:
        return ""
