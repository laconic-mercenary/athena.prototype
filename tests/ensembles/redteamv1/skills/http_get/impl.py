"""Skill: http_get — HTTP GET request."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

# Realistic browser UA — a bot-signature UA gets challenged by WAFs/Cloudflare on the way
# to OSINT targets, returning a challenge page instead of the real content.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


def _host_allowed(url: str) -> tuple[bool, str]:
    """Enforce the TOOLS_HTTP_OK_DOMAINS allowlist (CSV of domains) when that env var is set.
    Unset/empty → unrestricted (the var simply doesn't exist → ignore it). A request is allowed
    when its host equals an allowed entry or is a subdomain of one (so 'openintel.to' also allows
    'meridian.openintel.to'); bare IPs match exactly (e.g. '10.10.20.30')."""
    host = (urlparse(url).hostname or "").lower()
    allow = os.environ.get("TOOLS_HTTP_OK_DOMAINS", "").strip()
    if not allow:
        return True, host
    domains = [d.strip().lower().lstrip(".") for d in allow.split(",") if d.strip()]
    return (bool(host) and any(host == d or host.endswith("." + d) for d in domains)), host


def http_get(
    url: str,
    headers: dict | None = None,
    follow_redirects: bool = True,
) -> dict:
    allowed, host = _host_allowed(url)
    if not allowed:
        return {"url": url, "error": f"Blocked: host '{host}' not in TOOLS_HTTP_OK_DOMAINS allowlist"}
    merged = {**_HEADERS, **(headers or {})}
    try:
        with httpx.Client(timeout=15.0, verify=False, follow_redirects=follow_redirects) as client:
            r = client.get(url, headers=merged)
            return {
                "url": str(r.url),
                "status_code": r.status_code,
                "headers": dict(r.headers),
                "body": r.text[:4000],
            }
    except httpx.ConnectError as e:
        return {"url": url, "error": f"Connection refused or unreachable: {e}"}
    except httpx.TimeoutException:
        return {"url": url, "error": "Request timed out"}
    except httpx.RequestError as e:
        return {"url": url, "error": str(e)}
