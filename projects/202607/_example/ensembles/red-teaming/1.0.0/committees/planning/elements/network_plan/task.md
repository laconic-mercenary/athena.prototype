# Element: Network Plan

Analyse SSH and network-layer findings from ReconOutput and propose prioritised
attack actions targeting open ports, service versions, and network topology.

## What this element produces

A JSON array of PlannedAction objects covering network-layer attack vectors:
SSH credential reuse, version-based CVE exploitation, service enumeration,
network topology discovery via disclosed banners.

## Skills available

None — this is a pure reasoning element.

## Adequacy criterion (used by leader in compare mode)

Not applicable — this element runs in combine mode.
Output is adequate when at least one action is proposed with a rationale that
references a specific observation ID from the ReconOutput.
