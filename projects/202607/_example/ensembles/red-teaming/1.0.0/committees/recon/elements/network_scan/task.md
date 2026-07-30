# Element: network_scan

Enumerate open TCP ports and service versions on the target.

## Assignment template

Scan [TARGET: IP address, CIDR block, or hostname]
focusing on [SCOPE: port ranges or service types of interest, or "standard ports"]
at timing [TIMING: T1=stealthy / T2=cautious / T3=default / T4=aggressive]
excluding [EXCLUSIONS: hosts or ports to skip, or "none"].

## Output shape

JSON array of raw findings. One entry per tool call:
- `command` — tool name and key argument (e.g. "nmap_scan 10.0.1.5")
- `command_output` — full tool output
- `notes` — one-line factual note: which ports are open, what services

No classification. No interpretation beyond port state and service identity.

## Skills

- `nmap_scan(host)` — TCP connect scan across common ports with service version detection
- `check_port(host, port)` — single-port confirm; use to verify specific ports of interest

## Limitations

Does not probe at the protocol level — that is `service_probe`'s job.
Does not enumerate HTTP paths — that is `web_crawl`'s job.
Does not interpret findings or suggest next steps.

## Adequacy criterion

At least one `nmap_scan` call completed. Findings JSON is well-formed.
(Combine mode — not used in compare. This criterion is for the leader's
adequacy check when reviewing output before synthesis.)
