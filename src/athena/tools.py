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


ALLOWED_HOSTS: frozenset[str] = frozenset({"target"})

_HTTP_TIMEOUT = 10
_SOCKET_TIMEOUT = 5
_NMAP_TIMEOUT = 60
_MAX_BODY_BYTES = 65_536  # 64 KB

# Hardcoded port scope — callers cannot modify this.
_NMAP_PORTS = "21,22,23,25,53,80,110,143,443,445,3306,3389,5432,5900,6379,8080,8443,9200,27017"

_PORT_ENTRY_RE = re.compile(r"(\d+)/(open)/(\w+)//([^/]*)//([^/]*)")


# ---------------------------------------------------------------------------
# Guard functions
# ---------------------------------------------------------------------------


def _validate_host(host: str) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Host '{host}' is not in the allowed target list: {ALLOWED_HOSTS}")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"Host '{parsed.hostname}' is not in the allowed target list: {ALLOWED_HOSTS}"
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortInfo:
    port: int
    protocol: str
    state: str
    service: str
    version: str


@dataclass(frozen=True)
class NmapResult:
    host: str
    open_ports: tuple[PortInfo, ...]
    raw_output: str
    summary: str


@dataclass(frozen=True)
class PortCheckResult:
    host: str
    port: int
    is_open: bool
    latency_ms: float | None
    summary: str


@dataclass
class HttpGetResult:
    url: str
    status_code: int
    headers: dict[str, str]
    body: str
    summary: str


@dataclass
class HttpHeadResult:
    url: str
    status_code: int
    headers: dict[str, str]
    summary: str


@dataclass(frozen=True)
class SshBannerResult:
    host: str
    port: int
    banner: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class TcpBannerResult:
    host: str
    port: int
    banner: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class TlsProbeResult:
    host: str
    port: int
    tls_version: str | None
    cipher: str | None
    error: str | None
    summary: str


@dataclass(frozen=True)
class ExtractLinksResult:
    base_url: str
    links: tuple[str, ...]
    summary: str


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


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


def ssh_banner(host: str, port: int = 22) -> SshBannerResult:
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


class _LinkExtractor(HTMLParser):
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
