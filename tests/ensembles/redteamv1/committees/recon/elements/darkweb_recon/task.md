# darkweb_recon

Check dark-web / breach sources for exposure of the target company — one lookup per source.

1. `paste_site_search(query)`  — indexed paste aggregators.
2. `breach_db_search(query)`   — public breach compilations.
3. `leak_forum_search(query)`  — surface-indexed leak forums.
4. `onion_index_search(query)` — onion paste mirrors via surface index.

Use the company name or domain from your brief as the `query`.

**Output:** per-source hits (or "no matches"), and a note that all sources are surface-tier —
the deeper tier (paywalled DBs, invite-only forums, live onion services) was not queried, so
the leader can decide with the operator whether to dig further.
