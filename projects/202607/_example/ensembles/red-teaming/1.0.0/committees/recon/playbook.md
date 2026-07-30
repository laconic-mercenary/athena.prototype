# Recon Committee Playbook

## Element inventory

| Element          | What it does                                              | Task card |
|------------------|-----------------------------------------------------------|-----------|
| `network_scan`   | TCP port enumeration and service version detection        | elements/network_scan/task.md |
| `service_probe`  | Protocol-level banner and TLS fingerprinting              | elements/service_probe/task.md |
| `web_crawl`      | HTTP path enumeration and content extraction              | elements/web_crawl/task.md |
| `threat_analysis`| CVE and risk reasoning over accumulated findings (no tools) | elements/threat_analysis/task.md |

Read the task card for each element before writing your plan. The task card tells you
the assignment template, what the element produces, and what it cannot do.

---

## Standard sequencing

**Step 1 — parallel:** `network_scan` + `web_crawl`
Map the target simultaneously from the network layer and the application layer.
These two are independent — run them together.

**Step 2 — parallel:** `service_probe` on all open ports from step 1
service_probe needs the port list from step 1. Run all probe tasks in parallel
within this step. Write one task per host:port pair if the list is large.

**Step 3 — single:** `threat_analysis` over all step 1 + step 2 findings
Always runs last. Correlates version strings and banners across all gathered data.
Feed it the assembled raw text from network_scan, service_probe, and web_crawl.
threat_analysis cannot call tools — do not assign it any active work.

---

## When to adapt the standard pattern

- **Web-only target** (no TCP services expected beyond 80/443): skip `network_scan`.
- **Passive-only constraint from operator**: skip `service_probe` — banner probing is
  active and may be logged by the target. Note the gap in your plan.
- **Large CIDR range** (more than one /24): split `network_scan` into sub-tasks per
  subnet. Each sub-task is a separate task entry in the step.
- **Auth-required application paths**: `web_crawl` cannot authenticate. Record the
  gap explicitly in the plan so Planning knows which surface was not covered.
- **Explicit follow-up from threat_analysis**: if the operator approves a targeted
  follow-up after synthesis, add a step 4 with the specific element and scope.

---

## What the leader does not do

The leader classifies findings and writes the summary narrative. It does not run
tools itself, make network calls, or perform its own interpretation of raw findings
— that is threat_analysis's job. The leader's interpretation is the classification
decision (signal_critical / signal_warn / signal_info / noise / unknown).
