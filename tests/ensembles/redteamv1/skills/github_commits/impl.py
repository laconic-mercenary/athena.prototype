"""Skill: github_commits — read a public GitHub repo's commit history for leaked secrets."""

from __future__ import annotations

import os
import re

import httpx

_API = "https://api.github.com"
_UA = "redteam-osint/1.0"
_MAX_COMMITS = 20
_PATCH_MAX = 4000


def _parse_repo(repo: str) -> str | None:
    """Return 'owner/name' from 'owner/name' or a github.com URL, else None."""
    repo = (repo or "").strip()
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s#?]+)", repo)
    if m:
        owner, name = m.group(1), m.group(2)
    elif repo.count("/") == 1 and " " not in repo:
        owner, name = repo.split("/", 1)
    else:
        return None
    if name.endswith(".git"):
        name = name[:-4]
    return f"{owner}/{name}"


def _headers() -> dict:
    headers = {"User-Agent": _UA, "Accept": "application/vnd.github+json"}
    # Optional: a token raises the 60/hr unauthenticated limit. Not required for a demo.
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def repo_fetch(repo: str) -> dict:
    """First look at a repository: its metadata and top-level file listing.

    A source-code intelligence pass starts by orienting on the repo — what it is, its default
    branch, and which files exist (config, requirements, staging env files) — before digging the
    commit history for secrets. Input is "owner/name" or a github.com URL.
    """
    slug = _parse_repo(repo)
    if not slug:
        return {"error": f"Could not parse repo from {repo!r}; expected 'owner/name' or a github.com URL"}
    try:
        with httpx.Client(timeout=15.0, headers=_headers()) as client:
            r = client.get(f"{_API}/repos/{slug}")
            if r.status_code == 404:
                return {"repo": slug, "error": "Repository not found (or private)"}
            if r.status_code == 403:
                return {"repo": slug, "error": "GitHub API rate-limited or forbidden; set GITHUB_TOKEN to raise the limit"}
            r.raise_for_status()
            meta = r.json()
            top_level = []
            contents = client.get(f"{_API}/repos/{slug}/contents")
            if contents.status_code == 200 and isinstance(contents.json(), list):
                top_level = [
                    {"name": item.get("name", ""), "type": item.get("type", "")}
                    for item in contents.json()
                ]
            return {
                "repo": slug,
                "description": meta.get("description") or "",
                "default_branch": meta.get("default_branch", ""),
                "language": meta.get("language") or "",
                "pushed_at": meta.get("pushed_at", ""),
                "html_url": meta.get("html_url", ""),
                "top_level_files": top_level,
            }
    except httpx.HTTPError as e:
        return {"repo": slug, "error": f"GitHub API error: {e}"}


def github_commits(repo: str) -> dict:
    slug = _parse_repo(repo)
    if not slug:
        return {"error": f"Could not parse repo from {repo!r}; expected 'owner/name' or a github.com URL"}

    try:
        with httpx.Client(timeout=15.0, headers=_headers()) as client:
            r = client.get(f"{_API}/repos/{slug}/commits", params={"per_page": _MAX_COMMITS})
            if r.status_code == 404:
                return {"repo": slug, "error": "Repository not found (or private)"}
            if r.status_code == 403:
                return {"repo": slug, "error": "GitHub API rate-limited or forbidden; set GITHUB_TOKEN to raise the limit"}
            r.raise_for_status()

            commits = []
            for c in r.json():
                sha = c.get("sha", "")
                commit_meta = c.get("commit", {})
                author = commit_meta.get("author", {})
                files = []
                detail = client.get(f"{_API}/repos/{slug}/commits/{sha}")
                if detail.status_code == 200:
                    for f in detail.json().get("files", []):
                        patch = f.get("patch", "") or ""
                        files.append({
                            "filename": f.get("filename", ""),
                            "status": f.get("status", ""),
                            "patch": patch[:_PATCH_MAX],
                        })
                commits.append({
                    "sha": sha[:10],
                    "message": (commit_meta.get("message") or "").strip(),
                    "date": author.get("date", ""),
                    "author": author.get("name", ""),
                    "files": files,
                })
            return {"repo": slug, "commit_count": len(commits), "commits": commits}
    except httpx.HTTPError as e:
        return {"repo": slug, "error": f"GitHub API error: {e}"}
