# os_check

Best-effort OS fingerprint, run FIRST so the rest of the engagement knows Linux vs Windows.
Probe each OS family with its own focused check (all take `target` = IP/hostname from your brief):

1. `unix_type_check(target)`   — SSH + Linux-served HTTP (22, 80, 443).
2. `windows_smb_check(target)` — SMB / RPC / NetBIOS (135, 139, 445).
3. `windows_rdp_check(target)` — RDP / WinRM (3389, 5985).

Optionally `http_get` the target URL and read the `Server` header for extra signal.

**Output:** two lines —
```
OS: <Linux | Windows | Unknown>
Details: <distro/version + which family probe gave the evidence>
```

If inconclusive, output `OS: Unknown` and stop — do not re-probe. Recon proceeds regardless.
