"""Skill: http_get — HTTP GET request."""

from __future__ import annotations

import httpx

# Realistic browser UA — a bot-signature UA gets challenged by WAFs/Cloudflare on the way
# to OSINT targets, returning a challenge page instead of the real content.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


def http_get(
    url: str,
    headers: dict | None = None,
    follow_redirects: bool = True,
) -> dict:
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
