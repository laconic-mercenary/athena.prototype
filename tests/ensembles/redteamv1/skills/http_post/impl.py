"""Skill: http_post — HTTP POST request."""

from __future__ import annotations

import httpx

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; redteam-probe/1.0)"}


def http_post(
    url: str,
    body: str,
    headers: dict | None = None,
) -> dict:
    merged = {**_HEADERS, **(headers or {})}
    try:
        with httpx.Client(timeout=15.0, verify=False, follow_redirects=False) as client:
            r = client.post(url, content=body.encode(), headers=merged)
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
