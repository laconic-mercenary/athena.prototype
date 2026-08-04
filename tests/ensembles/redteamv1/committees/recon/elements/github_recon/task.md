# github_recon

Inspect the public repo (URL from the OSINT specialist) for secrets leaked in git history.

1. `github_commits(repo)` with the repository URL from your brief.
2. Scan the commit patches for values ADDED then later DELETED — internal IPs/hosts,
   credentials, or config files (e.g. a staging `.env`). These are gone from HEAD but
   recoverable from the earlier commit.

**Output:** each leaked host/IP (with port) and any other secret, plus the commit sha +
file it came from. The leaked host/IP is likely the engagement target.
