# Element: Risk Assessment

Assess overall risk severity and produce a prioritised list of remediation
recommendations based on what was discovered and retrieved.

## What this element produces

A JSON object with a title ("Risk Assessment"), a risk narrative (200-400 words),
a `risk_rating` enum value, and a `recommendations` list ordered by urgency.
Covers: overall severity, impact if exploited, likelihood, and specific actionable
remediation steps. Does not repeat raw findings.

## Skills available

None — pure reasoning element.

## Adequacy criterion

Output is adequate when `risk_rating` is one of `critical|high|medium|low` and
`recommendations` contains at least two specific, implementable steps (not generic
"patch your software" advice).
