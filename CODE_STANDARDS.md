# CODE_STANDARDS.md

> Shared engineering standards for this project. The `reviewer` and `safety` agents
> enforce these. Language-agnostic rules first; language- and protocol-specific rules in
> the appendix. When a rule and a framework requirement conflict, the framework wins ONLY
> where the framework genuinely requires it (e.g. pydantic/Textual classes) — never as a
> shortcut in our own domain logic.

---

## A. Correctness & style (language-agnostic)

1. **No silent defaults for meaningful values.** Never invent a default like
   `DEFAULT_USER = "admin"`. If a required value is unknown, ASK — do not guess a default.
   (Trivial, safe defaults like an empty list for an accumulator are fine; security- or
   identity-relevant defaults are not.)
2. **No magic numbers or strings.** Extract to named constants with meaning.
3. **Validate at interface transition boundaries.** Any value crossing an interface
   boundary (user input, network, file, another module's public API) is validated:
   strings checked for empty and length; numbers checked against bounds. Validation lives
   at the boundary, not scattered downstream.
4. **No None/null as a lazy substitute for handling a case.** Returning None to dodge a
   real case (that callers then forget to check) is not allowed — ASK instead. Idiomatic
   typed optionals (e.g. Python `Optional[T]`, explicit and checked) are fine.
5. **No infinite loops.** Every loop has a clear, bounded termination. Agent loops carry
   an explicit max-iteration cap.
6. **No global mutable variables.** (Language exception: Python module-level constants are
   fine; module-level *mutable* globals are not.)
7. **Comment the WHY, not the what.** Explain non-obvious decisions, trade-offs, and
   intent. Do NOT comment self-evident lines (no `i += 1  # increment i`). Well-named
   functions and variables carry the "what"; comments carry the "why" the code can't show.
   [NOTE: user originally specified "comment every line"; changed to why-not-what because
   line-by-line commenting reduces readability and drifts out of sync. Revert if desired.]
8. **Functions over ~20 lines get decomposed** into well-named sub-functions — UNLESS the
   whole is more readable kept together (documented exception: the Athena agent loop is
   intentionally ~40-60 lines in one piece). Decompose by default; keep-together only with
   a stated reason.
9. **Follow the language's idiomatic case conventions.** No custom casing schemes.
10. **Reusable code goes in its own modules.** Helpers (string validation, trimming,
    thematic reusable logic) live in dedicated helper modules, not inlined repeatedly.
11. **Don't reach for a library for a simple problem.** If it's simple, write it yourself.
    When unsure whether something crosses the "simple" threshold, ASK.

## B. Architecture (language-agnostic)

1. **Separate interface boilerplate from service code.** Interface/transport code (HTTP,
   TUI, CLI) is distinct from application service logic.
2. **Service modules contain no interface/transport specifics.** I should be able to swap
   HTTP for UDP (or TUI for web) and reuse the same service modules unchanged. Service code
   does not import HTTP/transport libraries.
3. **Abstract the storage layer behind an interface.** Critical-path code depends on a
   storage *interface*; implementation specifics (Postgres vs SQLite, etc.) live in their
   own modules behind that interface. When a boundary is unclear, ASK.
4. **External services get abstractions** — an interface or abstract class — never called
   raw from the critical path. (This is exactly the ModelBackend pattern.)
5. **Prefer functional/procedural over OO.** Structs/classes are fine for *data holding*
   and for *abstracting away implementations*; avoid OO as the primary paradigm for logic.

---

## Appendix: language- & protocol-specific

### Python
- Use type hints in all function signatures.
- Do NOT use inheritance in OUR code. (Exception: when a library/framework requires it —
  e.g. pydantic `BaseModel`, Textual widgets. The reviewer allows framework-required
  inheritance and flags inheritance only in our own domain logic.)
- Prefer functions to classes; classes acceptable for data holding (incl. pydantic models).
- Module-level constants fine; module-level mutable globals not.

### REST / HTTP services
- Treat ALL parameters and input as untrusted; every input MUST be validated.
- Verify request sizes; reject requests exceeding an appropriate byte limit.
- Enforce CORS.

### (Add further language-specific sections here as the project grows: Go, Rust, etc.)
