# web_osint

Passive web OSINT against the company's public site. You do NOT attack anything.

1. `http_get` the landing page (try `https://` then `http://` if the brief gives no scheme).
2. **Follow the links.** Enumerate every same-origin link (nav, body/CTA, footer) and `http_get`
   each distinct informational page (e.g. `/news`, `/blog`, `/engineering`) BEFORE concluding —
   the repository/client-library link usually lives one hop away, not on the landing page.
   - Same-origin only; skip off-site links, `mailto:`/`tel:`, and `#` placeholders; no duplicates.
3. From ALL pages read, extract: the tech stack, and any public code-repository URL
   (github.com / gitlab.com), captured full and verbatim.

**Output:** tech stack + repository URL (verbatim) + the pages you read. Do NOT report "no
repository" until you have followed the same-origin links — cite the pages you fetched.
