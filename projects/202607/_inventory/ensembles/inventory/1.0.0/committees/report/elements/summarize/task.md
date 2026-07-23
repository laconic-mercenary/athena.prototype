# Element: summarize

Turn a ScanOutput into a readable inventory report.

## Assignment template
Summarise the inventory of [DIRECTORY] from the ScanOutput:
a one-paragraph overview and a table of [EXTENSIONS] → count, with the total.

## Output shape
- `summary` — one short paragraph (what was inventoried, the headline numbers).
- `table_markdown` — a markdown table: `| extension | count |`.
- `total_files` — the total.

## Skills
None — reasoning only over the ScanOutput.

## Limitations
Do not re-count or access the filesystem. Use only the numbers in the ScanOutput.

## Adequacy criterion
The table lists every counted extension and the total matches the ScanOutput's `total_files`.
