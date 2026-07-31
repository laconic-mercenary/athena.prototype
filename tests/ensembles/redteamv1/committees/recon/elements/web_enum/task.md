# web_enum

Enumerate HTTP paths on the target web service.

Call `web_enum` with:
- `url`: base URL from your brief (e.g. "http://10.10.11.5")
- `wordlist_path`: wordlist path if specified in brief; omit to use the built-in list

**Output:** return the full web_enum result verbatim including `found` paths and `total_probed`.
If the URL is unreachable, return the error verbatim — the leader needs to know.
