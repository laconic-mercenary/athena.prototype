# Element: threat_analysis

CTI reasoning over accumulated raw findings. Identifies CVE candidates, risk
indicators, and recommended follow-up actions. Always runs last in the recon sequence.

## Assignment template

Analyse [FINDINGS: assembled raw text from network_scan, service_probe, and web_crawl —
paste all findings verbatim]
focusing on [FOCUS: specific service versions or vulnerability class of interest,
or "all findings"].

## Output shape

Structured markdown, exactly four sections:

```
## CVE Candidates
- CVE-XXXX-XXXXX — [service/version] — [why it applies]
- (none identified) if none apply

## Risk Indicators
- [specific exposed service, misconfiguration, or weak version]

## Recommended Follow-up
- [operator_name]: [precise action to take]

## Assessment
[1-2 sentences: the single most serious exposure and why it matters]
```

No JSON. No code blocks. At most 4 bullets per section. Lead with the finding —
no preamble, no restating the input.

## Model note

Runs on `foundation-sec-8b` via Ollama. Deep security domain knowledge but cannot
call tools. Receives pre-gathered findings as text and reasons analytically.
Do not assign any active work — findings must already be in the brief.

## Limitations

No tool calls — cannot verify findings against live systems. All output is analytical
reasoning, not confirmed exploitation. The leader must mark findings sourced from this
element as `unknown` classification unless confirmed by another element.
Generic filler output ("further investigation recommended" with no specifics) is a
failure — retry with a more focused brief.

## Adequacy criterion

All four sections present. Assessment contains a substantive primary risk statement
naming the specific service/version and the attack vector. Generic filler is not adequate.
(Combine mode — not used in compare. The adequacy criterion here is used by the leader
when deciding whether to accept the output or flag a retry.)
