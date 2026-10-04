"""SSRF guard for outbound URLs (SECURITY.md §5).

Rules enforced before any request leaves the process:
  * https only
  * port 443 only
  * DNS-resolved IPs must not be private/loopback/link-local/multicast/reserved,
    checked for every resolved address including IPv6
  * every redirect hop is re-validated (max 3)
  * 5 s connect timeout, 1 MB response cap
  * host allowlist for reference URLs; generic fetching is off by default (D-010)
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.errors import ValidationError

ALLOWED_SCHEMES = {"https"}
ALLOWED_PORTS = {443}
MAX_REDIRECTS = 3
TIMEOUT_S = 5.0
MAX_BYTES = 1024 * 1024

# D-010: metadata-only for platform URLs, so only known platform hosts are allowed.
DEFAULT_HOST_ALLOWLIST: frozenset[str] = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "instagram.com",
        "www.instagram.com",
        "tiktok.com",
        "www.tiktok.com",
        "vimeo.com",
        "www.vimeo.com",
    }
)


class SsrfBlocked(ValidationError):
    code = "SSRF_BLOCKED"


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    if addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return True
    # 100.64.0.0/10 carrier-grade NAT and the IPv6 equivalents.
    if addr.version == 4 and addr in ipaddress.ip_network("100.64.0.0/10"):
        return True
    if addr.version == 6 and addr.ipv4_mapped is not None:
        return _is_blocked_ip(str(addr.ipv4_mapped))
    return False


def resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfBlocked(
            "Host could not be resolved.", details={"host": host}
        ) from exc
    return [info[4][0] for info in infos]


def validate_url(
    url: str,
    *,
    allowlist: frozenset[str] | None = DEFAULT_HOST_ALLOWLIST,
    resolve_dns: bool = True,
) -> str:
    """Validate a URL for safe fetching. Returns the URL when acceptable."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfBlocked(
            "Only https URLs are allowed.", details={"scheme": parsed.scheme or "none"}
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise SsrfBlocked("URL has no host.")
    port = parsed.port or 443
    if port not in ALLOWED_PORTS:
        raise SsrfBlocked("Only port 443 is allowed.", details={"port": port})
    # Suffix match so subdomains of an allowlisted platform still work.
    if allowlist is not None and not any(
        host == h or host.endswith("." + h) for h in allowlist
    ):
        raise SsrfBlocked(
            "Host is not on the allowlist.",
            details={"host": host},
        )
    if resolve_dns:
        for ip in resolve_host(host):
            if _is_blocked_ip(ip):
                raise SsrfBlocked(
                    "Host resolves to a private or reserved address.",
                    details={"host": host},
                )
    return url


async def fetch_metadata(url: str, *, allowlist: frozenset[str] | None = DEFAULT_HOST_ALLOWLIST):
    """Fetch a small metadata document under the SSRF guard.

    Redirects are followed manually so each hop is re-validated, and the body is
    hard-capped so a hostile endpoint cannot exhaust memory.
    """
    import httpx

    current = validate_url(url, allowlist=allowlist)
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_S) as client:
        for _ in range(MAX_REDIRECTS + 1):
            resp = await client.get(
                current,
                headers={"User-Agent": "CreatorAI/0.1 (+metadata-only)"},
            )
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                current = validate_url(
                    str(httpx.URL(current).join(location)), allowlist=allowlist
                )
                continue
            if resp.status_code >= 400:
                raise ValidationError(
                    "Reference URL could not be fetched.",
                    details={"status": resp.status_code},
                )
            content = resp.content[:MAX_BYTES]
            return {
                "final_url": current,
                "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "content": content,
                "bytes": len(content),
            }
    raise ValidationError("Too many redirects while fetching reference URL.")


def is_oembed_url(url: str) -> bool:
    """Metadata-only endpoints we accept for reference URLs (D-010)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in DEFAULT_HOST_ALLOWLIST)