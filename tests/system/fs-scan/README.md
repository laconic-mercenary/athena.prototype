# fs-scan — Inventory Ensemble SIT

Runs the `inventory` ensemble against a known directory tree and expects specific
extension counts. This is the Phase 0–2 build target for the ensemble harness.

## Run / Stop

```
./run.sh    # build, start athena_web on :8001, print URL
./stop.sh   # tear down
```

## Ensemble

`ensemble/` — the inventory ensemble (manifest, schemas, committees, skills).
Mounted read-only into both containers at `/app/ensemble`.

## Test fixture

`testdata/` — mounted read-only at `/data/testfiles`. Deterministic layout:

| Extension | Count |
|-----------|-------|
| `.py`     | 11    |
| `.md`     | 4     |
| `.sh`     | 3     |
| `.sql`    | 3     |
| `.json`   | 3     |
| `.yml`    | 2     |
| `.html`   | 2     |
| `.css`    | 2     |
| `.js`     | 1     |
| `.csv`    | 1     |
| `.txt`    | 1     |
| `.toml`   | 1     |

**GREEN** = the ensemble produces a `ReportOutput` whose table matches the counts above.

## Notes

- Port `8001` (avoids conflict with the main stack on `8000`).
- `athena_runner` is defined in compose but assigned to the `runner` profile — not
  started by `run.sh`. Start it with `docker compose --profile runner up athena_runner`
  once the CLI mode is implemented.
- `count_extensions` skill requires its `ALLOWED_ROOTS` to include `/data`. Configure
  via env var when implementing the harness.
