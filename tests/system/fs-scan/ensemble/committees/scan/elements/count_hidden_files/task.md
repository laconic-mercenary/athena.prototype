# count_hidden_files

Walk the target directory and count hidden files (names starting with '.')
by extension using the count_hidden_files skill.

**Output:** raw JSON from count_hidden_files:
```json
{
  "directory": "<resolved path>",
  "counts": [{"extension": ".py", "count": N}, ...],
  "total_files": N,
  "skipped": []
}
```
