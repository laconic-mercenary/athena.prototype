# web_osint

Passive web OSINT against the company's public site.

1. `http_get` the landing page (try `https://` then `http://` if the brief gives no scheme).
2. Follow the clearest informational link (e.g. `/news`) with a second `http_get`.
3. From the HTML extract: the technology stack the company mentions, and any public
   code-repository URL (GitHub/GitLab), captured verbatim.

**Output:** tech stack + repository URL + the pages you read. No scanning or exploitation.
