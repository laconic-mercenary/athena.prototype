# os_check

Best-effort OS fingerprint, run FIRST so the rest of the engagement knows Linux vs Windows.

Call `nmap_scan` on OS-indicative ports for speed:
- `target`: IP or hostname from your brief
- `ports`: `"22,80,135,139,443,445,3389,5985"`
- `flags`: `"-sV -T4"`

Optionally call `http_get` on the target URL and read the `Server` header for extra signal.

**Output:** two lines —
```
OS: <Linux | Windows | Unknown>
Details: <distro/version + banner evidence>
```

If inconclusive, output `OS: Unknown` and stop — do not rescan. Recon proceeds regardless.
