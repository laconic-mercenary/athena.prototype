"""Deterministic tool layer for the Athena pipeline.

All tools validate the target host against ALLOWED_HOSTS before making any
network call. The LLM cannot influence which hosts are contacted or which
ports nmap scans — those are hardcoded here.
"""

from __future__ import annotations

import re
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


###############
# CONSTS / GLOBALS #
###############

ALLOWED_HOSTS: frozenset[str] = frozenset({"target"})
ALLOWED_DB_HOSTS: frozenset[str] = frozenset({"pgdatabase"})

_HTTP_TIMEOUT = 10
_SOCKET_TIMEOUT = 5
_NMAP_TIMEOUT = 60
_MAX_BODY_BYTES = 65_536  # 64 KB

# Hardcoded port scope — callers cannot modify this.
_NMAP_PORTS = "21,22,23,25,53,80,110,143,443,445,3306,3389,5432,5900,6379,8080,8443,9200,27017"

_PORT_ENTRY_RE = re.compile(r"(\d+)/(open)/(\w+)//([^/]*)//([^/]*)")


###############
# CUSTOM TYPES #
###############

@dataclass(frozen=True)
class PortInfo:
    """One open port entry parsed from nmap XML output.

    Contained in NmapResult.open_ports. Provides the parsed service name and
    version string so specialists can assess exposure without re-running nmap.
    """

    port: int
    protocol: str
    state: str
    service: str
    version: str


@dataclass(frozen=True)
class NmapResult:
    """Full result of an nmap scan against ALLOWED_HOSTS.

    Returned by nmap_scan(). Contains all parsed open ports and the raw nmap
    output for specialists that need more detail than the parsed fields provide.
    """

    host: str
    open_ports: tuple[PortInfo, ...]
    raw_output: str
    summary: str


@dataclass(frozen=True)
class PortCheckResult:
    """Result of a single TCP connect check to a specific host and port.

    Returned by check_port(). latency_ms is None if the port is closed or the
    connection attempt failed; is_open=False covers both refused and timed-out cases.
    """

    host: str
    port: int
    is_open: bool
    latency_ms: float | None
    summary: str


@dataclass
class HttpGetResult:
    """Result of an HTTP GET request to an ALLOWED_HOSTS target.

    Returned by http_get(). The body is capped at _MAX_BODY_BYTES (64 KB)
    to keep specialist context windows from being flooded by large responses.
    """

    url: str
    status_code: int
    headers: dict[str, str]
    body: str
    summary: str


@dataclass
class HttpHeadResult:
    """Result of an HTTP HEAD request — headers only, no body.

    Returned by http_head(). Used by specialists to probe server software
    and security headers without fetching the full response body.
    """

    url: str
    status_code: int
    headers: dict[str, str]
    summary: str


@dataclass(frozen=True)
class SshBannerResult:
    """Result of an SSH banner grab on an ALLOWED_HOSTS target.

    Returned by ssh_banner(). banner is None when the host does not respond
    on the given port; error carries the exception message in that case.
    """

    host: str
    port: int
    banner: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class TcpBannerResult:
    """Result of a passive TCP banner grab on an ALLOWED_HOSTS target.

    Returned by tcp_banner(). Connects and waits for a server-initiated banner
    (no probe is sent). Useful for services that speak first — FTP, SMTP, Redis.
    banner is None when the server sends nothing within the 3-second read timeout.
    """

    host: str
    port: int
    banner: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class TlsProbeResult:
    """Result of a TLS handshake probe against an ALLOWED_HOSTS target.

    Returned by tls_probe(). Captures the negotiated protocol version and cipher
    suite. error is non-None when the handshake fails (e.g. no TLS listener).
    """

    host: str
    port: int
    tls_version: str | None
    cipher: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class ExtractLinksResult:
    """Result of link extraction from an HTML page fetched from an ALLOWED_HOSTS target.

    Returned by extract_links(). Collects href, form action, and link href attributes,
    filtering out javascript:, mailto:, anchor, and data: URIs. Relative URLs are
    resolved against base_url before being returned.
    """

    base_url: str
    links: tuple[str, ...]
    summary: str


@dataclass
class PostgresQueryResult:
    """Result of a read-only SQL query against an ALLOWED_DB_HOSTS Postgres instance.

    Returned by postgres_query(). The host is validated against ALLOWED_DB_HOSTS before
    any connection attempt; credentials are supplied by the specialist as parameters.
    error is non-None when the query fails; in that case columns and rows are empty.
    """

    host: str
    database: str
    query: str
    columns: list[str]
    rows: list[list]
    row_count: int
    error: str | None
    summary: str


###############
# CLASSES #
###############

class _LinkExtractor(HTMLParser):
    """HTMLParser subclass that collects navigable links from an HTML document.

    Scans <a href>, <form action>, and <link href> tags, dropping javascript:,
    mailto:, anchor (#), and data: URIs. Used internally by extract_links().
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        href: str | None = None
        if tag == "a":
            href = attr_map.get("href")
        elif tag == "form":
            href = attr_map.get("action")
        elif tag == "link":
            href = attr_map.get("href")
        if href and not href.startswith(("javascript:", "mailto:", "#", "data:")):
            self.links.append(href)


###############
# FUNCTIONS #
###############

def nmap_scan(host: str) -> NmapResult:
    """TCP connect scan against hardcoded common port list. No LLM influence on scope."""
    _validate_host(host)
    proc = subprocess.run(
        [
            "nmap",
            "-sT",             # TCP connect (no raw sockets needed)
            "--open",          # only report open ports
            "-sV",             # service/version detection
            "--version-light", # lighter fingerprinting, less noise
            "-T3",             # normal timing
            "-p", _NMAP_PORTS,
            "-oG", "-",        # grepable output to stdout
            host,
        ],
        capture_output=True,
        text=True,
        timeout=_NMAP_TIMEOUT,
    )
    open_ports = _parse_nmap_grep(proc.stdout)
    if open_ports:
        port_list = ", ".join(f"{p.port}/{p.protocol} ({p.service})" for p in open_ports)
        summary = f"Found {len(open_ports)} open port(s) on {host}: {port_list}"
    else:
        summary = f"No open ports found on {host} in scanned range"
    return NmapResult(host=host, open_ports=open_ports, raw_output=proc.stdout, summary=summary)


def check_port(host: str, port: int) -> PortCheckResult:
    """TCP connect check on a single port."""
    _validate_host(host)
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=_SOCKET_TIMEOUT):
            latency_ms: float | None = (time.monotonic() - start) * 1000
            is_open = True
    except OSError:
        latency_ms = None
        is_open = False
    state = "open" if is_open else "closed"
    lat = f" ({latency_ms:.1f}ms)" if latency_ms is not None else ""
    summary = f"Port {host}:{port} is {state}{lat}"
    return PortCheckResult(host=host, port=port, is_open=is_open, latency_ms=latency_ms, summary=summary)


def http_get(url: str) -> HttpGetResult:
    """HTTP GET with bounded timeout and body size."""
    _validate_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Athena/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            status_code: int = resp.status
            headers: dict[str, str] = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read(_MAX_BODY_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status_code = e.code
        headers = {k.lower(): v for k, v in e.headers.items()}
        body = e.read(_MAX_BODY_BYTES).decode("utf-8", errors="replace")
    server = headers.get("server", "unknown")
    summary = f"GET {url} → {status_code}, server={server}, body={len(body)} chars"
    return HttpGetResult(url=url, status_code=status_code, headers=headers, body=body, summary=summary)


def http_head(url: str) -> HttpHeadResult:
    """HTTP HEAD — headers only, no body."""
    _validate_url(url)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Athena/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            status_code = resp.status
            headers: dict[str, str] = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        status_code = e.code
        headers = {k.lower(): v for k, v in e.headers.items()}
    server = headers.get("server", "unknown")
    content_type = headers.get("content-type", "unknown")
    summary = f"HEAD {url} → {status_code}, server={server}, content-type={content_type}"
    return HttpHeadResult(url=url, status_code=status_code, headers=headers, summary=summary)


def ssh_banner(host: str, port: int) -> SshBannerResult:
    """Read the SSH identification banner (the line the server sends immediately on connect)."""
    _validate_host(host)
    try:
        with socket.create_connection((host, port), timeout=_SOCKET_TIMEOUT) as sock:
            banner = sock.recv(256).decode("utf-8", errors="replace").strip()
        summary = f"SSH banner on {host}:{port}: {banner}"
        return SshBannerResult(host=host, port=port, banner=banner, error=None, summary=summary)
    except OSError as e:
        err = str(e)
        summary = f"SSH banner on {host}:{port} failed: {err}"
        return SshBannerResult(host=host, port=port, banner=None, error=err, summary=summary)


def tcp_banner(host: str, port: int) -> TcpBannerResult:
    """Connect and wait briefly for a server-initiated banner (no probe sent)."""
    _validate_host(host)
    try:
        with socket.create_connection((host, port), timeout=_SOCKET_TIMEOUT) as sock:
            sock.settimeout(3.0)
            try:
                raw = sock.recv(1024).decode("utf-8", errors="replace").strip()
            except socket.timeout:
                raw = ""
        if raw:
            summary = f"TCP banner on {host}:{port}: {raw[:80]!r}"
        else:
            summary = f"No banner received on {host}:{port} within timeout"
        return TcpBannerResult(host=host, port=port, banner=raw or None, error=None, summary=summary)
    except OSError as e:
        err = str(e)
        summary = f"TCP connect on {host}:{port} failed: {err}"
        return TcpBannerResult(host=host, port=port, banner=None, error=err, summary=summary)


def tls_probe(host: str, port: int) -> TlsProbeResult:
    """TLS handshake — reports negotiated version and cipher suite."""
    _validate_host(host)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=_SOCKET_TIMEOUT) as raw_sock:
            with ctx.wrap_socket(raw_sock, server_hostname=host) as ssl_sock:
                cipher_info = ssl_sock.cipher()
                tls_version = ssl_sock.version()
        cipher_str = cipher_info[0] if cipher_info else "unknown"
        summary = f"TLS on {host}:{port}: version={tls_version}, cipher={cipher_str}"
        return TlsProbeResult(
            host=host, port=port,
            tls_version=tls_version, cipher=cipher_str,
            error=None, summary=summary,
        )
    except OSError as e:
        err = str(e)
        summary = f"TLS probe on {host}:{port} failed: {err}"
        return TlsProbeResult(
            host=host, port=port,
            tls_version=None, cipher=None,
            error=err, summary=summary,
        )


def extract_links(html: str, base_url: str) -> ExtractLinksResult:
    """Parse HTML and return deduplicated absolute URLs resolved against base_url."""
    _validate_url(base_url)
    parser = _LinkExtractor()
    parser.feed(html)
    seen: set[str] = set()
    unique: list[str] = []
    for link in parser.links:
        resolved = urljoin(base_url, link)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    summary = f"Extracted {len(unique)} unique link(s) from {base_url}"
    return ExtractLinksResult(base_url=base_url, links=tuple(unique), summary=summary)


def postgres_query(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    query: str,
) -> PostgresQueryResult:
    """Execute a read-only SQL query against an allowed PostgreSQL host."""
    if host not in ALLOWED_DB_HOSTS:
        raise ValueError(
            f"Host '{host}' is not in the allowed DB target list: {ALLOWED_DB_HOSTS}"
        )
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError("psycopg2 is required for postgres_query — install psycopg2-binary")

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=username,
            password=password,
            connect_timeout=10,
            options="-c default_transaction_read_only=on",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in (cur.fetchall() if cur.description else [])]
        finally:
            conn.close()
        summary = f"Query on {host}/{database}: {len(rows)} row(s) returned"
        return PostgresQueryResult(
            host=host, database=database, query=query,
            columns=columns, rows=rows, row_count=len(rows),
            error=None, summary=summary,
        )
    except Exception as exc:
        return PostgresQueryResult(
            host=host, database=database, query=query,
            columns=[], rows=[], row_count=0,
            error=str(exc),
            summary=f"Query on {host}/{database} failed: {exc}",
        )


###############
# NON PUBLIC FUNCTIONS #
###############

def _validate_host(host: str) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Host '{host}' is not in the allowed target list: {ALLOWED_HOSTS}")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"Host '{parsed.hostname}' is not in the allowed target list: {ALLOWED_HOSTS}"
        )


def _parse_nmap_grep(output: str) -> tuple[PortInfo, ...]:
    ports: list[PortInfo] = []
    for line in output.splitlines():
        if not line.startswith("Host:"):
            continue
        match = re.search(r"Ports: (.+?)(?:\t|$)", line)
        if not match:
            continue
        for entry in match.group(1).split(", "):
            m = _PORT_ENTRY_RE.match(entry)
            if m:
                ports.append(
                    PortInfo(
                        port=int(m.group(1)),
                        protocol=m.group(3),
                        state="open",
                        service=m.group(4),
                        version=m.group(5),
                    )
                )
    return tuple(ports)
