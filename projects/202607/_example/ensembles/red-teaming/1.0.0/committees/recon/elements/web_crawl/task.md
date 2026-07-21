# Element: web_crawl

Enumerate HTTP/HTTPS paths and retrieve exposed content at the application layer.

## Assignment template

Crawl [BASE_URL: starting URL including protocol and port, e.g. "http://10.0.1.5:8080"]
probing [PATHS: specific paths of interest, or "standard path list"]
to depth [DEPTH: link-follow depth, e.g. "surface only" or "depth 2"]
looking for [FOCUS: forms / auth endpoints / admin paths / exposed files, or "all"].

## Standard path list (default when PATHS not specified)

`/`, `/robots.txt`, `/server-status`, `/server-info`, `/.well-known/`,
`/admin`, `/docs`, `/api`, `/files/`

## Output shape

JSON array of raw findings. One entry per HTTP call:
- `command` — method and URL (e.g. "GET http://10.0.1.5:8080/admin")
- `command_output` — status code, relevant headers, body excerpt (≤64 KB)
- `notes` — one-line factual note: what was found or confirmed absent

No classification.

## Skills

- `http_head(url)` — HEAD request; status and headers only (use for path existence checks)
- `http_get(url)` — GET request; status, headers, and body
- `extract_links(html, base_url)` — parses HTML, returns deduplicated absolute URLs

## Limitations

Cannot authenticate — auth-protected paths will return 401/403 and go no further.
Cannot render JavaScript — single-page apps will appear as empty shells.
Cannot follow redirects to out-of-scope domains.
Note any auth-required surfaces explicitly in output so the leader can flag the gap.

## Adequacy criterion

All assigned paths probed with `http_head`. Any path returning 2xx followed with
`http_get`. Extracted links within scope followed to the assigned depth.
(Combine mode — not used in compare.)
