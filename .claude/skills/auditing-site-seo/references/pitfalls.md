# Pitfalls

Each row is a mistake that actually happened during an audit, most of them by
the author of this skill. Re-read before reporting that something works.

## Verification

| Action | Reality |
|---|---|
| Eyeballing the page and calling it verified | Measure: computed colours, element positions in px, `scrollWidth == clientWidth`. A low-contrast label and a link 3.8 screens down both look "fine" in a screenshot. |
| Fixing the reported issue, assuming the score moves | One `color-contrast` failure came from **four separate CSS rules**; fixing three left the score at 96. Re-run the audit after every round. |
| `4.50:1` counts as passing | It rounds to 4.49 and fails. Aim for ≥ 4.8. |
| Trusting a self-made linter's score | The `opencode-seo` rules match **English** keywords. On a German site `no-cta` fires on a page with six `mailto:` CTAs and the score collapses to 0/100. It also counts an `<h1>` containing `<em>` as several H1s, requires the literal word "skip" for a skip link, and flags `Article`/`BreadcrumbList` on a one-page site. Use its structural rules; ignore its score. |
| Checking only the final HTTP status | A 301 → 302 → 200 chain is a bug. Count hops (`%{num_redirects}`). |
| Assuming a 200 means the page exists | Static sites with an SPA fallback answer every unknown URL with 200 + homepage. Check a path that cannot exist. |

## Structured data

| Action | Reality |
|---|---|
| Adding `priceRange` / `geo` / `openingHours` to clear a warning | Never invent structured data. Optional warnings stay; invented data is worse than a missing field. `Missing field 'priceRange' (optional)` is expected for a service business. |
| Reading the schema.org response as JSON directly | It is prefixed with `)]}'`. Strip the first line or `json.loads` fails. |
| Assuming the validator saw everything | Nested nodes (`publisher`, `founder`) arrive under `nodeProperties`, not as top-level items. Walk the tree before concluding a type is missing. |

## Deploy

| Action | Reality |
|---|---|
| `--tags user.docker.<svc>` alone | Silent no-op: `changed=0`, old checkout still served. Content arrives via `user.repo.clone`. Both tags, every time. |
| Committing locally, then deploying | The server pulls from `origin/master`. Unpushed = undeployed. |
| Seeing 404 right after a deploy and "fixing" it | Container needs ~40 s to report healthy; Traefik serves the error page meanwhile. |
| New nginx config deployed untested | A bad config means the container won't start and Traefik pulls the routers. `docker run --rm -v …:ro nginx:stable nginx -t` first, then a throwaway container on a spare port. |
| `Cache-Control: immutable` on everything static | Correct for hashed build output, wrong for unhashed files that change. Immutable promises the bytes at that URL never change. |

## Design and content

| Action | Reality |
|---|---|
| Putting a row of link buttons beside an existing similar list | Two near-identical 4-item lists where only some items correspond reads as a bug. Put links **inside** the structure that already exists. |
| Giving subpages their own header/sidebar | A 56 px gutter reserved but never filled, or a missing titleblock, makes them look like a different site. Chrome markup byte-identical across pages. |
| Publishing an example case report on a real business's site | A report number, client and findings that never existed is a fabricated credential. Label it as a methodology example or remove it. |
| Changing the brand colour to fix contrast | Brand colours often fail as *small text* while being fine as graphics. Add a darker text-only token; leave borders, arrows and fills alone. |
| Lifting a duplicated block instead of deleting it | If two blocks overlap partially, the fix is usually to delete one, not to move it. |

## Reporting

| Action | Reality |
|---|---|
| Reporting off-site work as done | Business Profile, citations and reviews need the owner's identity and Google's verification. "Registration complete, waiting for validation" is not a live listing — choosing "later" on verification means nothing was started. |
| Quoting a score without naming the tool | "SEO 100" means nothing. Say which authority, which mode, which device. Lighthouse *snapshot* mode measures accessibility/SEO but **not** performance — navigation mode needs a foreground window and will fail with `NO_FCP` otherwise. |
