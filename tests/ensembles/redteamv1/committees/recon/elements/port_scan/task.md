# port_scan

Run an nmap service and version scan against the target.

Call `nmap_scan` with:
- `target`: IP or hostname from your brief
- `ports`: range specified in your brief (default "1-1000")
- `flags`: flags from your brief (default "-sV -sC -T4")

**Output:** return the full nmap_scan result verbatim including `stdout` and `open_ports`.
