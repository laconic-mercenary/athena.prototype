"""Skill: web_enum — HTTP path enumeration using httpx."""

from __future__ import annotations

import os

import httpx

_BUILTIN_WORDLIST = [
    "/", "/.env", "/.git/HEAD", "/.htaccess", "/admin", "/admin/", "/api",
    "/api/v1", "/api/v2", "/backup", "/cgi-bin/", "/config", "/console",
    "/dashboard", "/db", "/debug", "/docs", "/download", "/favicon.ico",
    "/health", "/images", "/includes", "/index.php", "/info", "/info.php",
    "/js", "/login", "/login.php", "/logout", "/phpmyadmin", "/register",
    "/robots.txt", "/server-status", "/sitemap.xml", "/static", "/status",
    "/swagger", "/swagger-ui.html", "/test", "/upload", "/uploads", "/user",
    "/users", "/wp-admin", "/wp-login.php", "/xmlrpc.php",
]

_TIMEOUT = 5.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; redteam-scanner/1.0)"}


def web_enum(url: str, wordlist_path: str | None = None) -> dict:
    base = url.rstrip("/")
    paths = _load_wordlist(wordlist_path)
    found = []
    errors = 0

    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, verify=False, follow_redirects=False) as client:
        for path in paths:
            target = base + path
            try:
                r = client.get(target)
                if r.status_code != 404:
                    found.append({
                        "path": path,
                        "status_code": r.status_code,
                        "size": len(r.content),
                    })
            except httpx.ConnectError:
                errors += 1
                if errors >= 5:
                    return {
                        "base_url": base,
                        "error": "Too many connection errors — target may be unreachable",
                        "found": found,
                        "total_probed": len(paths),
                    }
            except httpx.RequestError:
                errors += 1

    return {
        "base_url": base,
        "found": found,
        "total_probed": len(paths),
    }


def _load_wordlist(path: str | None) -> list[str]:
    if path and os.path.isfile(path):
        with open(path) as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        return [ln if ln.startswith("/") else "/" + ln for ln in lines]
    return _BUILTIN_WORDLIST
