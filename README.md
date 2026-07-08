# athena.prototype

Athena is a proof-of-concept agent committee pipeline. A human issues one instruction; an
orchestrator summons specialist committees that each do a phase of work, emit an artifact,
and hand off to the next committee.

The demo runs a fully-authorized red team engagement against a local Docker target:
recon → planning → retrieval → reporting.

Full documentation in `ATHENA_README.md`. Standing rules for coding agents in `AGENTS.md`.
