# Element: service_probe

Probe discovered services at the protocol level for banners, version strings,
and TLS configuration.

## Assignment template

Probe [TARGETS: list of host:port pairs discovered in step 1]
using [PROTOCOL_HINTS: ssh / tcp / tls per port, or "determine from service name"]
to collect [FOCUS: banner strings / TLS cipher suites / version identifiers, or "all"].

## Output shape

JSON array of raw findings. One entry per tool call:
- `command` — tool name and arguments (e.g. "ssh_banner 10.0.1.5 22")
- `command_output` — full tool output
- `notes` — one-line factual note: banner content, TLS version, cipher suite

No classification.

## Skills

- `ssh_banner(host, port)` — reads the SSH identification string on connect
- `tcp_banner(host, port)` — waits for a server-initiated banner (FTP, SMTP, custom services)
- `tls_probe(host, port)` — performs TLS handshake; reports negotiated version and cipher suite

## Limitations

Active probing — each call makes a real network connection and will appear in target logs.
Do not assign in passive-only engagements.
Cannot authenticate or send probe payloads beyond the initial connect.
Needs network_scan output to know which ports exist — always runs after step 1.

## Adequacy criterion

All assigned host:port pairs probed with the appropriate skill.
(Combine mode — not used in compare.)
