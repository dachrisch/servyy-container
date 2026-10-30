#!/usr/bin/env python3
"""Verify a live site against the authorities that actually matter.

Read-only. No dependencies beyond the standard library.

    python3 verify-site.py https://example.com
    python3 verify-site.py https://example.com --paths / /about.html
    python3 verify-site.py https://example.com --skip-w3c   # faster, no rate limit
    python3 verify-site.py https://example.com --json

Checks, per page:
  - HTTP 200
  - exactly one <h1>
  - no heading-level skips (h1 -> h3)
  - every JSON-LD block parses
  - W3C Nu HTML Checker errors/warnings     (validator.w3.org)
  - schema.org structured data problems     (validator.schema.org)

Site-wide:
  - every URL listed in sitemap.xml returns 200
  - Cache-Control present on representative assets
  - <link rel=canonical> present on every checked page

Exit code 0 only if everything passes, so it can gate a deploy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; site-verify/1.0)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx instead of following it.

    schema.org answers a throttled request with a 302 to an HTML rate-limit
    page; urllib would follow it, turn the POST into a GET and hand back HTML
    that fails to parse as JSON. Seeing the 3xx lets us report "rate limited"
    instead of "unreachable".
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)

# States returned by the remote validators.
OK, RATE_LIMITED, ERROR = "ok", "rate-limited", "error"



def fetch(url: str, data: bytes | None = None, timeout: int = 60) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def head(url: str, timeout: int = 30) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def strip_xssi(raw: str) -> str:
    """schema.org's endpoint prefixes JSON with )]}' (XSSI guard)."""
    if raw.startswith(")]}'"):
        return raw.split("\n", 1)[1] if "\n" in raw else raw[4:]
    return raw


def w3c_check(page_url: str) -> tuple[str, int, int, str]:
    """Returns (state, errors, warnings, first message)."""
    q = urllib.parse.quote(page_url, safe="")
    try:
        with urllib.request.urlopen(f"https://validator.w3.org/nu/?doc={q}&out=json",
                                    timeout=90) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308, 429):
            return RATE_LIMITED, -1, -1, "rate limited"
        return ERROR, -1, -1, f"HTTP {e.code}"
    except Exception as e:
        return ERROR, -1, -1, type(e).__name__
    try:
        msgs = json.loads(body.decode("utf-8", "replace")).get("messages", [])
    except Exception:
        return ERROR, -1, -1, "unparseable response"
    errs = [m for m in msgs if m.get("type") == "error"]
    warns = [m for m in msgs if m.get("type") == "info" and m.get("subType") == "warning"]
    first = errs[0].get("message", "")[:110] if errs else ""
    return OK, len(errs), len(warns), first


def schema_check(page_url: str) -> tuple[str, int, list[str]]:
    """Returns (state, problem count, first few problems)."""
    data = urllib.parse.urlencode({"url": page_url}).encode()
    req = urllib.request.Request(
        "https://validator.schema.org/validate", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    try:
        with _OPENER.open(req, timeout=90) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308, 429):
            return RATE_LIMITED, -1, ["rate limited by validator.schema.org"]
        return ERROR, -1, [f"HTTP {e.code}"]
    except Exception as e:
        return ERROR, -1, [type(e).__name__]
    try:
        doc = json.loads(strip_xssi(raw))
    except Exception:
        return ERROR, -1, ["unparseable response"]

    problems: list[str] = []

    def walk(node):
        for e in node.get("errors", []):
            problems.append(str(e.get("error", ""))[:110])
        for p in node.get("properties", []):
            for e in p.get("errors", []):
                problems.append(f"{p.get('pred')}: {e.get('error', '')}"[:110])
        for np in node.get("nodeProperties", []):
            walk(np.get("target", {}))

    for g in doc.get("tripleGroups", []):
        for n in g.get("nodes", []):
            walk(n)
    return OK, len(problems), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="base URL, e.g. https://example.com")
    ap.add_argument("--paths", nargs="*", default=["/"],
                    help="paths to check (default: /)")
    ap.add_argument("--skip-w3c", action="store_true")
    ap.add_argument("--skip-schema", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    report: dict = {"base": base, "pages": {}, "site": {}}
    failures = 0

    for path in args.paths:
        url = base + path
        status, body, _ = fetch(url)
        html = body.decode("utf-8", "replace")
        entry: dict = {"status": status}

        heads = [int(m) for m in re.findall(r"<h([1-6])[ >]", html)]
        entry["h1_count"] = heads.count(1)
        entry["heading_skips"] = [[a, b] for a, b in zip(heads, heads[1:]) if b > a + 1]
        entry["canonical"] = bool(re.search(r'<link[^>]+rel=["\']canonical', html))

        ld_blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.S)
        bad_ld = 0
        for b in ld_blocks:
            try:
                json.loads(b)
            except Exception:
                bad_ld += 1
        entry["jsonld_blocks"] = len(ld_blocks)
        entry["jsonld_invalid"] = bad_ld

        skipped = []
        if not args.skip_w3c:
            st, e, w, first = w3c_check(url)
            entry["w3c_state"], entry["w3c_errors"], entry["w3c_warnings"] = st, e, w
            entry["w3c_first"] = first
            if st != OK:
                skipped.append(f"w3c ({first})")
            time.sleep(1.5)  # the W3C endpoint rate-limits
        if not args.skip_schema and ld_blocks:
            st, n, names = schema_check(url)
            entry["schema_state"], entry["schema_problems"] = st, n
            entry["schema_first"] = names[:3]
            if st != OK:
                skipped.append(f"schema.org ({names[0]})")
            time.sleep(1.0)
        entry["skipped"] = skipped

        # A throttled validator is not a site defect - never fail on it.
        # -1 means "did not run", which is not evidence of a problem.
        local_ok = (status == 200 and entry["h1_count"] == 1 and not entry["heading_skips"]
                    and entry["jsonld_invalid"] == 0 and entry["canonical"])
        remote_ok = (entry.get("w3c_errors", 0) in (0, -1)
                     and entry.get("schema_problems", 0) in (0, -1))
        ok = local_ok and remote_ok
        entry["ok"] = ok
        if not ok:
            failures += 1
        report["pages"][path] = entry

    # ---- site-wide -------------------------------------------------------
    # Soft-404: a static site with an SPA-style `try_files $uri $uri/ /index.html`
    # answers every unknown URL with 200 + the homepage. Invisible in a browser,
    # but it feeds Google infinite duplicates. Ask for a path that cannot exist.
    probe = "/.verify-nonexistent-" + str(int(time.time())) + "/"
    s, body, _ = fetch(base + probe)
    looks_like_home = b'rel="canonical"' in body and len(body) > 500
    soft404_ok = s in (404, 410)
    report["site"]["soft_404"] = {
        "path": probe, "status": s,
        "ok": soft404_ok,
        "note": "unknown URL returns 200 (SPA fallback?)" if not soft404_ok else "correctly 404s",
        "homepage_body": looks_like_home and not soft404_ok,
    }
    if not soft404_ok:
        failures += 1

    status, body, _ = fetch(base + "/sitemap.xml")
    text = body.decode("utf-8", "replace") if status == 200 else ""
    is_xml = text.lstrip().startswith("<?xml") or "<urlset" in text or "<sitemapindex" in text
    if not is_xml:
        # Astro emits /sitemap-index.xml; some setups only expose that.
        st2, body2, _ = fetch(base + "/sitemap-index.xml")
        txt2 = body2.decode("utf-8", "replace") if st2 == 200 else ""
        if txt2.lstrip().startswith("<?xml") or "<sitemapindex" in txt2 or "<urlset" in txt2:
            status, text = st2, txt2
            is_xml = True

    def collect_locs(doc: str) -> list[str]:
        """Handles both <urlset> and <sitemapindex> (Astro emits an index)."""
        locs = re.findall(r"<loc>([^<]+)</loc>", doc)
        if "<sitemapindex" in doc:
            resolved: list[str] = []
            for idx in locs:
                s2, b2, _ = fetch(idx)
                if s2 == 200:
                    resolved += re.findall(r"<loc>([^<]+)</loc>", b2.decode("utf-8", "replace"))
            return resolved
        return locs

    sm_ok, sm_bad = 0, []
    urls = collect_locs(text) if is_xml else []
    for loc in urls:
        s, _ = head(loc)
        if s == 200:
            sm_ok += 1
        else:
            sm_bad.append(f"{loc} -> {s}")
    report["site"]["sitemap_status"] = status
    report["site"]["sitemap_is_xml"] = is_xml
    report["site"]["sitemap_urls_ok"] = sm_ok
    report["site"]["sitemap_urls_bad"] = sm_bad
    if not is_xml or not urls or sm_bad:
        failures += 1

    assets = report["site"]["cache_control"] = {}
    for asset in ("/", "/robots.txt", "/sitemap.xml"):
        s, h = head(base + asset)
        assets[asset] = h.get("Cache-Control") or h.get("cache-control") or "MISSING"
        if assets[asset] == "MISSING":
            failures += 1
    if sm_bad or status != 200:
        failures += 1

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"site: {base}\n")
        for path, e in report["pages"].items():
            flag = "PASS" if e["ok"] else "FAIL"
            if e["ok"] and e.get("skipped"):
                flag = "PASS"  # remote checks did not run, local ones did
            print(f"  [{flag}] {path}" + ("   (remote checks skipped: " + "; ".join(e["skipped"]) + ")" if e.get("skipped") else ""))
            print(f"         http={e['status']} h1={e['h1_count']} skips={e['heading_skips'] or '-'} "
                  f"jsonld={e['jsonld_blocks']}({e['jsonld_invalid']} invalid) canonical={e['canonical']}")
            if "w3c_errors" in e:
                print(f"         w3c: {e['w3c_errors']} errors, {e['w3c_warnings']} warnings"
                      + (f"  <- {e['w3c_first']}" if e.get("w3c_first") else ""))
            if "schema_problems" in e:
                print(f"         schema.org: {e['schema_problems']} problems"
                      + (f"  <- {e['schema_first'][0]}" if e.get("schema_first") else ""))
        sf = report["site"]["soft_404"]
        print(f"\n  soft-404: {sf['status']} for {sf['path']} -> {sf['note']}")
        print(f"  sitemap.xml: {status} (xml={report['site']['sitemap_is_xml']}) - "
              f"{sm_ok} urls ok, {len(sm_bad)} bad {sm_bad[:3] or ''}")
        print("  cache-control:")
        for k, v in assets.items():
            print(f"         {k:14s} {v}")
        print(f"\nRESULT: {'ALL PASS' if failures == 0 else str(failures) + ' FAILURE(S)'}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
