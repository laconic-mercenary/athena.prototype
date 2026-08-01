# cve_lookup

Search ExploitDB for known exploits against the services discovered in Step 1.

Your brief will list discovered services and versions. Call `searchsploit` once with
the single most promising query — format: `"<service> <version>"` (e.g. "Apache 2.4.49").

**Prioritise:**
1. Web framework or CMS with a specific version
2. SSH with an old version (< 7.4)
3. Any other service with a non-default or old version string

**Output:** return the searchsploit result verbatim. If it returns no results, say so —
the leader will reason from model CVE knowledge.
