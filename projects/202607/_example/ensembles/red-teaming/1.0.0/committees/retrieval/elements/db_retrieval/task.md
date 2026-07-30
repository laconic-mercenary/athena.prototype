# Element: DB Retrieval

Execute database-layer planned actions using credentials discovered during recon.
Enumerate schema, retrieve table contents, surface secrets and sensitive data.

## What this element produces

A JSON array of RetrievedFinding objects. Each finding records a postgres_query call,
the action_id it was executing, the SQL query and key result excerpt, and a note of
what the data means for the engagement.

## Skills available

- `postgres_query(host, port, database, username, password, query)` — read-only SQL
  query against an allowed PostgreSQL host. Credentials must come from ReconOutput.

## Adequacy criterion

Output is adequate when: schema discovery has been performed (list tables), and
each discovered table has been queried for its contents. Credential source must be
traceable to a specific observation in ReconOutput.
