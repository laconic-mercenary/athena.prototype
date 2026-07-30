# count_regular_files

Walk the target directory and count non-hidden files (names not starting with '.')
by extension using the count_regular_files skill.

**Output:** raw JSON from count_regular_files:
```json
{
  "directory": "<resolved path>",
  "counts": [{"extension": ".py", "count": N}, ...],
  "total_files": N,
  "skipped": []
}
```
