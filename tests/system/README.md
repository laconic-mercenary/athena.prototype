# System Integration Tests

Each subdirectory is a self-contained scenario: its own `docker-compose.yml`, `run.sh`,
`stop.sh`, ensemble, and test fixtures.

| Scenario | What it tests |
|----------|---------------|
| `fs-scan/` | Inventory ensemble — count files by extension in a known directory tree |
