"""Skills: dark-web / breach reconnaissance, one tool per source.

DEMO NOTE: these are simulated OSINT sources. Each models ONE surface-tier source so the
analyst makes several distinct, realistic lookups (rather than a single generic call). For a
target with no public breach exposure they legitimately return nothing, and each flags that a
deeper (paywalled / invite-only) tier was not queried — that is what prompts the operator beat.
None of these reach the network.
"""

from __future__ import annotations


def _no_hits(source: str, query: str, tier_note: str) -> dict:
    return {
        "source": source,
        "query": query,
        "hits": [],
        "result": "no matches",
        "coverage": "surface-indexed only",
        "deeper_tier_available": True,
        "note": tier_note,
    }


def paste_site_search(query: str) -> dict:
    """Search indexed paste aggregators (Pastebin / Ghostbin surface index)."""
    return _no_hits(
        "Paste aggregators (Pastebin / Ghostbin surface index)",
        query,
        "Only the public paste index was searched; expired and members-only pastes were not.",
    )


def breach_db_search(query: str) -> dict:
    """Search public breach compilations (Collection-style aggregated dumps)."""
    return _no_hits(
        "Public breach compilations",
        query,
        "Free aggregated dumps only; paywalled breach databases were not queried.",
    )


def leak_forum_search(query: str) -> dict:
    """Search surface-indexed leak / hacking forums."""
    return _no_hits(
        "Surface-indexed leak forums",
        query,
        "Public threads only; invite-only and registration-walled forums were not accessed.",
    )


def onion_index_search(query: str) -> dict:
    """Search Tor/onion paste mirrors reachable through a surface index."""
    return _no_hits(
        "Onion paste mirrors (surface-indexed)",
        query,
        "Surface-reachable mirrors only; live onion services requiring Tor were not crawled.",
    )
