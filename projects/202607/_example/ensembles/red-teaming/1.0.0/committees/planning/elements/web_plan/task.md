# Element: Web Plan

Analyse HTTP, Apache, and web-layer findings from ReconOutput and propose prioritised
attack actions targeting exposed files, misconfigurations, and credential chains.

## What this element produces

A JSON array of PlannedAction objects covering web-layer attack vectors:
exposed credential file retrieval, Apache misconfiguration exploitation,
credential chain follow-through, path enumeration targets.

## Skills available

None — this is a pure reasoning element.

## Adequacy criterion

Output is adequate when the actions reference specific paths or files observed
in the ReconOutput web findings, with observation IDs cited.
