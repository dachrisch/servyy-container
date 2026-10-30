# Google Business Profile, citations, Search Console

This half cannot be done for the site owner. It needs their Google account,
their identity and Google's verification. **You prepare the data; you never
report it as completed.**

## 1. Search Console — do this first

Nothing else is measurable until it exists. Prefer a **Domain property**
(`sc-domain:<domain>`) — it covers apex, `www` and both protocols.

- Verify by DNS TXT. For Porkbun-managed domains the API keys already live in
  `ansible/plays/vars/secrets.yml` (git-crypt), so the record can be written
  without a manual click-through.
- Then submit `sitemap.xml` and use **URL Inspection → Request indexing** on the
  pages that matter. The sitemap alone is slow (days); request indexing is fast.
- Check the property type the owner actually created. A URL-prefix property
  verified over HTTP will not cover the other protocol or host.

## 2. Business Profile — the local channel

Only the owner can do this, and **verification must be started**: choosing
"Später bestätigen" leaves the listing unverified and not live, which is easy to
mistake for "pending".

Data pack to prepare (paste-ready, exact character counts):

- **Name** — the real trading name, nothing added. Keyword-stuffing the name is
  a suspension risk.
- **Primary category** — the most specific that is true (e.g. `Architekt`).
  Wrong or too-generic categories suppress local visibility. Secondaries only
  if genuinely applicable.
- **Address / phone** — byte-identical to the Impressum and to the site footer.
  Inconsistent NAP is the classic local-SEO failure.
- **Website** — the apex, with the canonical form.
- **Description** — ≤ 750 chars, factual, no superlatives, no invented claims.
  Count it: `python3 -c 'print(len(open("desc.txt").read()))'`.
- **Services** — one entry per real service, matching the site's pages.
- **Photos** — real ones, ≥ 720 px wide. A 300 px image is not usable.

**Verification method.** Video is usually offered first and is usually fastest:
one continuous unedited take from the street/signage through the premises, with
business documents (Gewerbe, Kammer letter, invoice) in frame. Postcard is
reliable but 1–2 weeks. Pick deliberately — a wrong address in that flow costs
weeks.

**Before soliciting reviews or running ads**, check the applicable professional
advertising rules. For German architects and similar *Kammer* professions this is
the **Berufsordnung / Sachlichkeitsgebot**, which is stricter than ordinary
trade law. Reviews themselves are fine; how you ask can be regulated.

## 3. Citations (after the listing is verified)

Same name, address and phone everywhere — that consistency *is* the citation.

| Where | Notes |
|---|---|
| Bing Places | also feeds Copilot; can be done before Google verification finishes |
| Apple Business Connect | Apple Maps |
| Bayerische Architektenkammer / relevant chamber directory | often the highest-trust citation; check the entry links to the site |
| Gelbe Seiten, 11880, Das Örtliche | German standard set |

## 4. Order of operations

1. Search Console + sitemap + request indexing
2. Business Profile: start verification
3. On-page and technical work (the checklist) — do not wait for verification
4. Citations once the listing exists
5. Reviews last, after the advertising rules are cleared

## 5. What to check afterwards

- GSC → **Pages**: is everything "Indexed"? Anything "Discovered – currently not
  indexed" is a crawl-budget or link problem, not a content problem.
- GSC → **Performance**: real queries after 2–4 weeks. Zero impressions with an
  indexed site means the pages target nothing anyone searches for.
- Core Web Vitals field data needs traffic. On a new site "no data" for weeks is
  normal; judge by lab numbers until then.
