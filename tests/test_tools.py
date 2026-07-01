"""Tests for the tool layer.

Live network tests (nmap, http_get, etc.) require the docker-compose stack.
These tests cover: host guards, URL guards, and pure-logic tools (extract_links).
"""

import pytest

from athena.tools import (
    ExtractLinksResult,
    check_port,
    extract_links,
    http_get,
    http_head,
    nmap_scan,
    ssh_banner,
    tcp_banner,
    tls_probe,
    _validate_host,
    _validate_url,
)


# ---------------------------------------------------------------------------
# Host / URL guards
# ---------------------------------------------------------------------------


def test_validate_host_allows_target() -> None:
    _validate_host("target")  # must not raise


def test_validate_host_blocks_external() -> None:
    with pytest.raises(ValueError, match="not in the allowed target list"):
        _validate_host("example.com")


def test_validate_host_blocks_localhost() -> None:
    with pytest.raises(ValueError):
        _validate_host("localhost")


def test_validate_url_allows_target() -> None:
    _validate_url("http://target/foo")  # must not raise


def test_validate_url_blocks_external() -> None:
    with pytest.raises(ValueError, match="not in the allowed target list"):
        _validate_url("http://example.com/foo")


@pytest.mark.parametrize("fn,args", [
    (nmap_scan,    ("8.8.8.8",)),
    (check_port,   ("8.8.8.8", 80)),
    (http_get,     ("http://example.com/",)),
    (http_head,    ("http://example.com/",)),
    (ssh_banner,   ("8.8.8.8", 22)),
    (tcp_banner,   ("8.8.8.8", 80)),
    (tls_probe,    ("8.8.8.8", 443)),
    (extract_links, ("<a href='/'>home</a>", "http://example.com/")),
])
def test_all_tools_block_external_hosts(fn, args) -> None:
    with pytest.raises(ValueError, match="not in the allowed target list"):
        fn(*args)


# ---------------------------------------------------------------------------
# extract_links — pure logic, no network
# ---------------------------------------------------------------------------


def test_extract_links_resolves_relative_hrefs() -> None:
    html = '<a href="/about">About</a><a href="/contact">Contact</a>'
    result = extract_links(html, "http://target/")
    assert "http://target/about" in result.links
    assert "http://target/contact" in result.links


def test_extract_links_deduplicates() -> None:
    html = '<a href="/page">One</a><a href="/page">Two</a>'
    result = extract_links(html, "http://target/")
    assert result.links.count("http://target/page") == 1


def test_extract_links_skips_javascript_and_mailto() -> None:
    html = (
        '<a href="javascript:void(0)">JS</a>'
        '<a href="mailto:admin@target">Mail</a>'
        '<a href="/real">Real</a>'
    )
    result = extract_links(html, "http://target/")
    assert len(result.links) == 1
    assert result.links[0] == "http://target/real"


def test_extract_links_includes_form_actions() -> None:
    html = '<form action="/submit" method="post"></form>'
    result = extract_links(html, "http://target/")
    assert "http://target/submit" in result.links


def test_extract_links_summary_reflects_count() -> None:
    html = '<a href="/a">A</a><a href="/b">B</a>'
    result = extract_links(html, "http://target/")
    assert "2" in result.summary


def test_extract_links_empty_html_returns_empty_tuple() -> None:
    result = extract_links("<p>No links here</p>", "http://target/")
    assert result.links == ()
    assert isinstance(result, ExtractLinksResult)
