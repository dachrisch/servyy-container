# SEO checklist — ordered

Do these in order. Each phase assumes the previous one is green.
`<base>` = the public URL, e.g. `https://xn--hfer-architekten-mwb.de`.

## 0. Recon (5 min, don't skip)

```bash
cd servyy-container/<service>
cat AGENTS.md 2>/dev/null          # per-site conventions, deploy command
grep -n "volumes\|image:" docker-compose.yml
```

Static (`./serve` mounted) → edit `serve/`, nginx in `nginx/default.conf`.
Image (`image: bumblecode/x`) → source is another repo; find it, edit there.

Note the service's own `AGENTS.md` before anything else — it encodes traps
(dateirechte, world_readable_paths, "don't shorten the references list").

## 1. Baseline — measure before changing anything

```bash
python3 servyy-container/.claude/skills/auditing-site-seo/scripts/verify-site.py <base> --paths / ...
```

Plus Lighthouse (DevTools or `pagespeed.web.dev`). Record the numbers; you
cannot prove improvement without a baseline.

Expect `Core Web Vitals: no data` on a new site — CrUX needs real traffic. Lab
numbers only. That is normal, not a failure.

## 2. Indexability & metadata

- `<title>` ≤ 60 chars, unique per page, keyword-first
- `<meta name="description">` ≤ 160 chars, unique, written to earn the click
- `<link rel="canonical">` absolute, on **every** page
- `<html lang="de">` (or correct language)
- `robots.txt` allows, points at the sitemap
- `sitemap.xml` lists every page, absolute URLs, `<lastmod>` updated
- `llms.txt` if the site has one — add new pages to it
- OG + Twitter tags (`og:title`, `og:description`, `og:image` 1200×630, `og:url`)

```bash
curl -sS <base>/sitemap.xml | grep -c "<loc>"      # count vs pages you know
```

## 2a. Soft-404s and redirect hygiene

Static sites inherit two traps from their nginx config. Both are invisible in a
browser and both are cheaper to fix than any content work.

- **`try_files $uri $uri/ /index.html`** — an SPA fallback copied onto a static
  site. Every unknown URL then answers **200 with the homepage**. Google sees
  infinite duplicates and wastes crawl budget.

  ```bash
  curl -o /dev/null -w '%{http_code}\n' <base>/verify-not-a-page/   # must be 404
  ```

- **Missing `absolute_redirect off;`** — nginx builds `Location:` from the
  internal port-80 origin, so a directory redirect hands out `http://` and every
  internal hop costs an extra round trip.

Count hops, not just the final status:

```bash
for p in / /services /about; do
  echo "$p hops=$(curl -sIL -o /dev/null -w '%{num_redirects}' <base>$p)"
done    # 0 or 1; a chain of 301 -> 302 -> 200 is a bug
```

A trailing-slash mismatch turns every internal link into a redirect. Fix it at
the source (the templates), not with a redirect rule.

## 3. Structured data

Build one `@graph` in `<head>`: the business (`ProfessionalService` /
`LocalBusiness`), the `Person` behind it, `WebSite`. Subpages add `Service` +
`BreadcrumbList` (+ `FAQPage`).

Rules:
- **Only data visible on the page.** No invented `geo`, `priceRange`,
  `openingHours`, `sameAs`.
- Cross-reference with `@id` (`{base}/#business`, `/#person`).
- Validate: `POST https://validator.schema.org/validate` with `url=<url>`;
  the response starts with `)]}'` — strip that line before parsing JSON.
- `Missing field 'priceRange' (optional)` is expected and correct to ignore.

## 4. Semantics & accessibility

- Exactly **one** `<h1>`; no heading-level skips (h1 → h2 → h3)
- Exactly **one** `<main>` per page — a layout wrapper plus a page-level `<main>`
  is a duplicate landmark and invalid markup
- `.skip-link` as the first focusable element, target `#main`
- Landmarks: `<main>`, `<header>`, `<nav aria-label="…">`, `<footer>`
- Every `<img>`: descriptive `alt`, `width`+`height`, `loading="lazy"` below the
  fold — and a global `img{height:auto}` or the attributes distort the image
- Contrast ≥ 4.5:1 for text under 24px. Brand colours often fail as *text*:
  add a darker text-only token instead of changing the brand colour

```bash
# Lighthouse Accessibility must be 100. Re-run after EVERY fix round -
# one failing audit can come from several different CSS rules.
```

## 5. Performance

- Self-host web fonts (woff2, latin subset) — for German sites this is also a
  DSGVO matter (LG München I, 3 O 17493/20); no `fonts.googleapis.com`
- `rel="preload"` the two most-used faces; `font-display: swap`
- Inline the CSS for a one-pager; no third-party requests at all
- Verify: zero third-party hosts in the network panel

```bash
curl -sS <base> | grep -c "fonts.googleapis"     # must be 0
```

## 6. Caching (nginx)

Per path class — see `references/nginx-cache.md` for the ready-made block:

| Path | Cache-Control |
|---|---|
| `*.html` | `max-age=0, must-revalidate` |
| fonts, hashed build assets | `max-age=31536000, immutable` |
| unhashed CSS that changes | `max-age=3600` |
| images | `max-age=604800` |
| robots/sitemap/llms | `max-age=3600` |

**Immutable only where the filename changes with the content.** `add_header`
does not inherit: once a `location` sets its own, server-level ones stop
applying to it.

Validate syntax *before* deploying — a bad config means the container won't
start and Traefik pulls the routers:

```bash
docker run --rm -v "$PWD/nginx/default.conf":/etc/nginx/conf.d/default.conf:ro nginx:stable nginx -t
```

## 7. Host hygiene

- `www` → apex **301/308**, path and query preserved
- Any preview/staging hostname (`*.lehel.xyz`) → `X-Robots-Tag: noindex, nofollow`
  on **that router only**; verify the public domain has **no** such header
- Canonical on every page points at the apex

```bash
curl -sSI https://www.<domain>/ | grep -iE "^HTTP|^location"
curl -sSI https://<alias>/ | grep -i x-robots-tag      # expect noindex
curl -sSI https://<domain>/ | grep -i x-robots-tag     # expect nothing
```

## 8. Internal linking

Links go **inside the structure that already exists** (a service row's heading,
a matching list item, a footer nav). Never a new block beside a similar list.

Measure discoverability, don't eyeball it:

```js
// in the browser console: how many screens down is the link block?
const y = window.scrollY + document.querySelector('.that-block').getBoundingClientRect().top;
y / window.innerHeight
```

Three-plus screens down is effectively unfindable. Header nav or the section
the visitor already reads.

## 9. Content

- One page per service and search intent — a single-page site for a multi-service
  business caps its reach
- Every page: a 40–60 word answer block directly under the H1 (snippets, AI
  Overviews), real specifics, no filler
- **No fabricated projects, case reports or credentials.** If there is no real
  data, present the method and say so
- Cross-link sibling pages

## 10. Deploy

```bash
git add -A && git commit && git push origin master      # server pulls from origin
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,user.<service>
sleep 40 && docker ps --filter name=<service> --format '{{.Status}}'   # healthy?
```

Then **re-verify live** with `verify-site.py` and a fresh Lighthouse run.
Deployed ≠ working; the restart window alone will fool you.

## 11. Off-site (owner required)

See `references/google-business-profile.md`.
