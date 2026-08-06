# github_recon

Inspect the public repo (URL from the OSINT specialist) for secrets leaked in git history.

1. `repo_fetch(repo)` FIRST — orient on the repository: description, default branch, language,
   and top-level files. Note config/requirements/staging-env files worth checking in history.
2. `github_commits(repo)` — scan the commit patches for values ADDED then later DELETED —
   internal IPs/hosts, credentials, or config files (e.g. a staging `.env`). These are gone from
   HEAD but recoverable from the earlier commit.

**Output:** each leaked host/IP (with port) and any other secret, plus the commit sha + file it
came from. The leaked host/IP is likely the engagement target.
