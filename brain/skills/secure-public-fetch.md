---
title: Fetch user-given public URLs safely
tags: security, fetch, ssrf, dns, redirects, mcp
agents: forge, coder
learned_from: 12
related: mcp-connector, escalate-one-hop, learn-a-skill
---
## When to use
Any tool or server that fetches a URL a user or Claude gives it. Without these checks, a
fetch tool can be pointed at the host's own network (localhost, cloud metadata at 169.254.169.254, LAN).

## How
1. Parse the URL. Allow only `http:` and `https:`. Reject URLs with credentials (`user:pass@`). Allow only ports 80, 443, 8080 and 8443 (job 12's list).
2. Check the address at connection time, not only from the URL text. Pass a custom `lookup` to the HTTP client that resolves with `dns.lookup(host, { all: true })`, rejects every private address, and only then connects. This also stops DNS-rebinding tricks.
3. Block these ranges (IPv4 and IPv4-mapped IPv6): 0/8, 10/8, 100.64/10 (CGNAT), 127/8, 169.254/16 (metadata), 172.16/12, 192.168/16, 224/4 (multicast), 240/4 (reserved), plus the IPv6 loopback, link-local (fe80::/10), unique-local (fc00::/7) and `::ffff:` forms of all the above.
4. Follow redirects by hand: `redirect: "manual"`, run the same check on each hop, stop after 5.
5. Limit time and size: 10-second timeout, and a download cap (job 12 used 3 MB) that cuts the page off and tells the reader it was cut.
6. Rate-limit the endpoint per client IP (job 12: 60/min), and cache fetched pages briefly (10 min) so an outline and a read don't download twice.
7. Test it: each blocked range, a redirect to 127.0.0.1, a hostname that resolves to a private address, and a credentialed URL should all fail, and a normal public page should pass.

## Gotchas
- Checking the URL string alone is not enough: a public name can resolve to 127.0.0.1.
- Mapped IPv6 forms such as `::ffff:10.0.0.1` slip past plain IPv4 checks.
- Don't follow redirects automatically; the second hop can go somewhere private.
- If the server is open with no secret, anyone who finds it can use your bandwidth. Say so in the README.
