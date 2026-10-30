---
name: auditing-site-seo
description: Use when auditing or improving the search visibility of a site in servyy-container (höfer-architekten.de, bumbleflies.de, leaguesphere.app or any service dir), when someone asks for an "SEO score", "SEO check", "why doesn't my site show up on Google", "make it findable", when a new site is about to launch, or when verifying that a previous SEO claim is actually true.
---

# Auditing Site SEO

## Overview

Only measurements from the authorities Google and the web actually use count.
A self-made linter's score is one vendor's opinion, not a measurement.

**Core principle: verify against an authority, or don't claim it.**

## First: which kind of site is this?

Nothing works until you know. Read `<service>/docker-compose.yml`.

| | Static files in this repo | Separate source repo → image |
|---|---|---|
| Example | `achim-hoefer/` (`serve/` bind-mounted) | `bumbleflies/` → `bumbleflies/web` repo (Astro) |
| HTML lives in | `serve/*.html` | the other repo's `src/` |
| nginx config | `nginx/default.conf` here | `nginx.conf` there, baked into the image |
| Deploy | `servyy.sh --tags user.repo.clone,user.<svc>` | push source → CI builds image → compose pulls |

A bare `image:` with no `./serve` mount means **the HTML is elsewhere**.

## Quick reference — the five authorities

| Question | Authority | How |
|---|---|---|
| HTML valid? | W3C Nu | `validator.w3.org/nu/?doc=<url>&out=json` |
| Structured data valid? | schema.org | `POST validator.schema.org/validate`, body `url=<url>`; strip the `)]}'` prefix |
| Fast / accessible? | Google Lighthouse | DevTools or `pagespeed.web.dev`; **needs the window in the foreground** |
| Rich results? | Rich Results Test | `search.google.com/test/rich-results?url=<url>` |
| Actually indexed? | Search Console | only ground truth; owner's login |

`scripts/verify-site.py <base> --paths / /page.html` checks the factual half in
one pass: status, one `<h1>`, heading order, canonical, JSON-LD parses, W3C,
schema.org, soft-404, sitemap URLs, cache headers. Exits non-zero on failure, so
it can gate a deploy. A throttled validator is reported as *skipped*, never as a
site defect.

**Both external validators rate-limit hard** — a handful of runs per hour. Batch
pages; don't loop.

## Workflow

`references/checklist.md` — the ordered audit with exact commands. Follow it top
to bottom: indexability before content, content before off-site.

`references/nginx-cache.md` — cache and redirect config for both site flavours.

`references/google-business-profile.md` — Search Console, Business Profile,
citations, reviews. Needs the owner; you prepare data, you cannot complete it.

`references/pitfalls.md` — the mistakes that actually cost time here, most of
them observed. **Read before claiming anything works.**

## The three that cost the most

1. **Deploy silently does nothing** without `user.repo.clone` in `--tags`
   (`changed=0`, old checkout still served), and the commit must be on
   `origin/master` first.
2. **404 right after a deploy is the restart window**, ~40 s until the container
   reports healthy. Check `docker ps` before "fixing" anything.
3. **`Cache-Control: immutable` on unhashed assets** (`plan.css`,
   `public/images/*`) gives returning visitors a stale file for a year. Only
   where the filename changes with the content.
