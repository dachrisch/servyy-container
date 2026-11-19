#!/usr/bin/env python3
"""Render and verify the service landscape.

The map (`architecture/landscape.yaml`, git-crypt encrypted) is the source of truth
for the architecture view. This script keeps it honest and turns it into the
DocStash artifact:

  --verify     diff the map against the repository (compose files + db_tenants.yml)
               and exit non-zero on drift. This is the only reason the map is
               worth keeping: a map nobody checks is decoration.
  --build      print the mechanical fields as YAML to paste back into the map,
               after a --verify run told you what moved. It never rewrites the
               file: comments are curated content and PyYAML would eat them.
  --html       render the artifact (a self-contained HTML page) from the map alone.
  --selftest   parse the repository and assert the derivation still works. CI runs
               this, because CI cannot decrypt the map (no git-crypt key) — it
               proves the tool, not the map.

Usage:
  python3 architecture/render.py --verify
  python3 architecture/render.py --html > /tmp/architecture.html
  python3 architecture/render.py --selftest
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

HOST_RE = re.compile(r"Host\(`([^`]+)`\)")
CONTAINER_VAR = re.compile(r"\$\{COMPOSE_PROJECT_NAME\}")


# --------------------------------------------------------------------------- #
# repository derivation
# --------------------------------------------------------------------------- #
def compose_files(repo: Path) -> list[Path]:
    return sorted(p for p in repo.glob("*/docker-compose.yml") if p.is_file())


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def derive(repo: Path, ignore_projects: list[str]) -> dict[str, dict[str, Any]]:
    """Derive containers, their project and their public domains from compose files."""
    derived: dict[str, dict[str, Any]] = {}
    for path in compose_files(repo):
        project = path.parent.name
        data = load_yaml(path) or {}
        for name, cfg in (data.get("services") or {}).items():
            cfg = cfg or {}
            raw = cfg.get("container_name") or f"{project}.{name}"
            container = CONTAINER_VAR.sub(project, str(raw))
            labels = cfg.get("labels") or {}
            if isinstance(labels, list):  # `- key=value` form
                labels = dict(
                    str(item).split("=", 1) for item in labels if "=" in str(item)
                )
            domains: set[str] = set()
            templated = False
            for key, value in labels.items():
                if "traefik" in str(key) and ".rule" in str(key):
                    for host in HOST_RE.findall(str(value)):
                        # `${SERVICE_HOST}` is substituted by `docker compose up`
                        # from the rendered .env, so the compose TEXT cannot say
                        # what the container actually serves. Those hosts are
                        # curated in the map instead (domains_rendered: true).
                        if "${" in host:
                            templated = True
                        else:
                            domains.add(host)
            entry = derived.setdefault(
                container,
                {"project": project, "image": cfg.get("image"),
                 "domains": set(), "templated": False},
            )
            entry["domains"] |= domains
            entry["templated"] = entry["templated"] or templated
    for container, entry in derived.items():
        entry["ignored"] = entry["project"] in ignore_projects
    return derived


def derive_tiers(repo: Path) -> dict[str, dict[str, Any]]:
    """Read db_tenants.yml: which server each engine/tenant sits on."""
    path = repo / "ansible" / "plays" / "vars" / "db_tenants.yml"
    data = load_yaml(path) or {}
    tiers: dict[str, dict[str, Any]] = {}
    for row in data.get("db_tenants") or []:
        tier = row.get("tier")
        if not tier:
            continue
        slot = tiers.setdefault(tier, {"servers": {}, "tenants": []})
        slot["servers"][row["server"]] = row.get("engine")
        slot["tenants"].append(row.get("tenant"))
    return tiers


def derive_live(host: str, timeout: int = 60) -> dict[str, dict[str, Any]]:
    """Ask a host what its containers actually serve.

    The compose files in this repository render most hostnames from `${SERVICE_HOST}`
    at deploy time, so their text cannot verify anything — but `docker inspect` on
    the host can. Requires ssh access; CI does not have it, humans do.
    """
    cmd = [
        "ssh", "-o", "BatchMode=yes", host,
        "docker ps -q | xargs -r docker inspect",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise SystemExit(f"cannot reach {host} for --verify-host: {exc}") from exc
    if out.returncode != 0:
        raise SystemExit(f"cannot inspect containers on {host}: {out.stderr.strip()}")
    data = json.loads(out.stdout or "[]")
    live: dict[str, dict[str, Any]] = {}
    for item in data:
        name = item["Name"].lstrip("/")
        labels = item["Config"].get("Labels") or {}
        domains: set[str] = set()
        for key, value in labels.items():
            if "traefik" in str(key) and ".rule" in str(key):
                domains.update(HOST_RE.findall(str(value)))
        live[name] = {"domains": domains}
    return live


def verify_live(lmap: dict[str, Any], live: dict[str, dict[str, Any]], host: str) -> list[str]:
    """Compare the map's domain lists with what the containers on `host` serve.

    Domains belong to the STACK, not to one container: in the LeagueSphere projects
    the `www` container holds the router and the `app` container talks to the
    database, so comparing per container would report every domain as missing.
    """
    problems: list[str] = []
    for svc in lmap.get("services") or []:
        if svc.get("host", "servy.lehel.xyz") != host:
            continue
        have: set[str] = set()
        seen = 0
        for container in svc.get("containers") or []:
            entry = live.get(container)
            if entry is None:
                if not svc.get("optional"):
                    problems.append(f"{svc['id']}: {container} is not running on {host}")
                continue
            seen += 1
            have |= entry["domains"]
        if not seen:
            continue
        want = set(svc.get("domains") or [])
        for missing in sorted(want - have):
            problems.append(f"{svc['id']}: map lists {missing}, {host} does not serve it")
        for extra in sorted(have - want):
            problems.append(f"{svc['id']}: {host} serves {extra}, which the map does not list")
    return problems


def compose_images(repo: Path) -> dict[str, str]:
    """container -> image, for containers declared in compose files."""
    images: dict[str, str] = {}
    for path in compose_files(repo):
        project = path.parent.name
        for name, cfg in ((load_yaml(path) or {}).get("services") or {}).items():
            cfg = cfg or {}
            raw = cfg.get("container_name") or f"{project}.{name}"
            images[CONTAINER_VAR.sub(project, str(raw))] = cfg.get("image")
    return images


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify(lmap: dict[str, Any], repo: Path) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    templated: list[str] = []
    derived = derive(repo, lmap.get("ignore_projects") or [])

    mapped: set[str] = set()
    for svc in lmap.get("services") or []:
        sid = svc.get("id", "?")
        containers = svc.get("containers") or []
        if not containers:
            problems.append(f"{sid}: no containers[] — it maps nothing")
            continue
        if svc.get("external_compose"):
            # The stack's compose file lives in another repository (the app's own),
            # so this checkout cannot derive its containers or labels. The tier
            # checks below still apply; the domain list is curated.
            mapped.update(containers)
            continue
        for container in containers:
            mapped.add(container)
            derived_name = svc.get("compose_container") or container
            mapped.add(derived_name)
            got = derived.get(derived_name)
            if got is None:
                problems.append(
                    f"{sid}: container {derived_name} does not exist in any compose file"
                )
                continue
            if got["templated"]:
                # Rendered hostnames: the map is the only place they are written
                # down, so there is nothing to compare against. Say so once.
                templated.append(derived_name)
                continue
            want = set(svc.get("domains") or [])
            have = set(got["domains"])
            for missing in sorted(want - have):
                problems.append(
                    f"{sid}: map lists {missing}, but {derived_name} has no Traefik rule for it"
                )
            for extra in sorted(have - want):
                problems.append(
                    f"{sid}: {derived_name} serves {extra}, which the map does not list"
                )

    for container, entry in sorted(derived.items()):
        if container in mapped or entry["ignored"]:
            continue
        if entry["domains"] or entry["templated"]:
            shown = ", ".join(sorted(entry["domains"])) or "a rendered host"
            problems.append(
                f"unmapped: {container} publishes {shown} "
                "but no service in the map owns it"
            )

    tiers = derive_tiers(repo)
    for name, tier in (lmap.get("tiers") or {}).items():
        actual = tiers.get(name)
        if actual is None:
            problems.append(f"tier {name}: no row in db_tenants.yml")
            continue
        declared = set(tier.get("tenants") or [])
        if declared != set(actual["tenants"]):
            problems.append(
                f"tier {name}: map tenants {sorted(declared)} != inventory "
                f"{sorted(actual['tenants'])}"
            )
        for server in tier.get("servers") or []:
            if server["name"] not in actual["servers"]:
                problems.append(
                    f"tier {name}: server {server['name']} is not in db_tenants.yml"
                )
    for name in sorted(set(tiers) - set(lmap.get("tiers") or {})):
        problems.append(f"tier {name}: exists in db_tenants.yml but not in the map")

    images = compose_images(repo)
    for tier in (lmap.get("tiers") or {}).values():
        for server in tier.get("servers") or []:
            declared = server.get("image")
            actual = images.get(server["name"])
            if declared and actual and declared != actual:
                problems.append(
                    f"{server['name']}: map says {declared}, compose says {actual}"
                )

    return problems, templated


def build(lmap: dict[str, Any], repo: Path) -> str:
    """Print the mechanical fields as YAML, for pasting back into the map."""
    derived = derive(repo, lmap.get("ignore_projects") or [])
    out: list[str] = []
    for svc in lmap.get("services") or []:
        containers = svc.get("containers") or []
        domains: set[str] = set()
        for container in containers:
            domains |= (derived.get(container) or {}).get("domains", set())
        out.append(f"  - id: {svc['id']}")
        out.append(f"    containers: [{', '.join(containers)}]")
        out.append(f"    domains: [{', '.join(sorted(domains))}]")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# html
# --------------------------------------------------------------------------- #
CSS = """
  :root{
    --paper:#f6f5f1; --card:#fffefb; --ink:#14161a; --muted:#5d6470; --line:#e2dfd6;
    --high:#6d5efc; --nonprod:#d98324; --business:#0f8b8d; --private:#b3446c; --ext:#6b7280;
    --radius:14px; --mono:'JetBrains Mono',ui-monospace,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:'Space Grotesk',system-ui,sans-serif;line-height:1.5}
  .wrap{max-width:1120px;margin:0 auto;padding:56px 24px 88px}
  header{border-bottom:1px solid var(--line);padding-bottom:28px;margin-bottom:36px}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
  h1{font-size:clamp(30px,4.4vw,52px);line-height:1.05;margin:10px 0 14px;letter-spacing:-.02em;font-weight:700}
  .lede{font-size:17px;color:#3c424c;max-width:70ch;margin:0}
  .stats{display:flex;flex-wrap:wrap;gap:26px;margin-top:26px}
  .stat b{display:block;font-size:26px;font-weight:600;letter-spacing:-.01em}
  .stat span{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  h2{font-size:13px;font-family:var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:52px 0 16px;font-weight:600}
  h3{font-size:15px;margin:0 0 10px;font-weight:600}
  .spine{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;align-items:stretch}
  .node{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px 14px 16px;position:relative}
  .node .k{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
  .node .v{font-size:14px;font-weight:600;margin-top:6px;line-height:1.3}
  .node .s{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:6px}
  .node:not(:last-child):after{content:"\\2192";position:absolute;right:-13px;top:50%;transform:translateY(-50%);color:#b9b5a9;font-size:16px;z-index:2}
  @media(max-width:860px){.spine{grid-template-columns:1fr}.node:not(:last-child):after{content:"\\2193";right:50%;top:auto;bottom:-16px;transform:translateX(50%)}}
  .group{margin-top:30px}
  .row{display:grid;grid-template-columns:minmax(220px,1.15fr) minmax(200px,1fr) minmax(220px,1fr);gap:16px;padding:12px 14px;border-top:1px solid var(--line);align-items:baseline}
  .row:last-child{border-bottom:1px solid var(--line)}
  .row.head{border-top:none;font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);padding-bottom:6px}
  .host{font-family:var(--mono);font-size:13px;word-break:break-word}
  .host small{display:block;color:var(--muted);font-size:11.5px;margin-top:2px}
  .svc{font-size:14px}
  .cont{display:block;font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-top:2px}
  .data{font-family:var(--mono);font-size:12px;color:#3c424c}
  @media(max-width:820px){.row{grid-template-columns:1fr;gap:4px}.row.head{display:none}}
  .chip{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:999px;border:1px solid;margin-right:7px;vertical-align:1px}
  .c-high{color:var(--high);border-color:#c9c3fb;background:#f2f0ff}
  .c-nonprod{color:var(--nonprod);border-color:#f0d3ae;background:#fdf5ea}
  .c-business{color:var(--business);border-color:#aadbd9;background:#eefafa}
  .c-private{color:var(--private);border-color:#e6bccd;background:#fdf1f5}
  .c-ext{color:var(--ext);border-color:#d6d8dd;background:#f4f5f7}
  .tiers{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
  @media(max-width:760px){.tiers{grid-template-columns:1fr}}
  .tier{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px 18px;border-top:3px solid #b9b5a9}
  .tier.high{border-top-color:var(--high)}.tier.nonprod{border-top-color:var(--nonprod)}
  .tier.business{border-top-color:var(--business)}.tier.private{border-top-color:var(--private)}
  .tier .t{font-size:14px;font-weight:600;margin-bottom:2px}
  .tier .srv{font-family:var(--mono);font-size:12px;color:#3c424c}
  .tier ul{margin:10px 0 0;padding-left:16px;font-size:13px;color:#3c424c}
  .tier li{margin:3px 0}
  .tier .note{font-size:12px;color:var(--muted);margin-top:10px}
  .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  @media(max-width:860px){.cards{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px}
  .card p{margin:0;font-size:13.5px;color:#3c424c}
  .rules{margin:0;padding:0;list-style:none;counter-reset:r}
  .rules li{position:relative;padding:14px 16px 14px 52px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:10px;font-size:14px}
  .rules li:before{counter-increment:r;content:counter(r);position:absolute;left:16px;top:14px;font-family:var(--mono);font-size:12px;color:var(--muted);width:22px;height:22px;border:1px solid var(--line);border-radius:50%;display:grid;place-items:center}
  .rules b{display:block;margin-bottom:2px}
  .foot{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);font-family:var(--mono);font-size:11.5px;color:var(--muted)}
"""

TIER_CLASS = {"high": "c-high", "nonprod": "c-nonprod", "business": "c-business", "private": "c-private"}
DATA_KIND_CHIP = {
    "none": None,
    "mariadb": None,
    "mongo": None,
    "sqlite": "SQLite",
    "volume": None,
    "external": "external",
    "tsdb": "TSDB",
}


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def split_hosts(domains: list[str]) -> tuple[str, list[str]]:
    """First domain is the headline; the rest go small underneath."""
    if not domains:
        return "", []
    primary = min(domains, key=lambda d: (d.startswith("www."), len(d)))
    return primary, [d for d in sorted(domains) if d != primary]


def data_cell(svc: dict[str, Any]) -> str:
    data = svc.get("data") or {}
    kind = data.get("kind", "none")
    if kind == "none":
        return '<span class="chip">stateless</span>'
    if kind == "external":
        return f'<span class="chip c-ext">external</span>{e(data.get("where", ""))}'
    if kind in ("sqlite", "volume", "tsdb"):
        chip = f'<span class="chip">{e(kind)}</span>'
        return f'{chip}{e(data.get("where", ""))}'
    tier = next(
        (name for name, t in TIERS.items() if data.get("server") in {s["name"] for s in t.get("servers", [])}),
        None,
    )
    chip = f'<span class="chip {TIER_CLASS.get(tier, "")}">{e(tier or kind)}</span>' if tier else ""
    suffix = f' · <em>{e(data["db"])}</em>' if data.get("db") else ""
    return f'{chip}{e(data.get("server", ""))}{suffix}'


TIERS: dict[str, Any] = {}


def render_html(lmap: dict[str, Any]) -> str:
    global TIERS
    TIERS = lmap.get("tiers") or {}

    services = lmap.get("services") or []
    domains = sorted({d for s in services for d in (s.get("domains") or [])})
    groups = lmap.get("groups") or []
    group_order = [g["id"] for g in groups]

    parts: list[str] = []
    parts.append(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body><div class="wrap">
<header>
  <div class="eyebrow">servy.lehel.xyz · service shape · {e(lmap.get('as_of', ''))}</div>
  <h1>{e(lmap.get('title', 'Architecture'))}</h1>
  <p class="lede">{e(lmap.get('subtitle', ''))}</p>
  <div class="stats">
    <div class="stat"><b>{len(domains)}</b><span>public hostnames</span></div>
    <div class="stat"><b>{len(lmap.get('tiers') or {})}</b><span>data tiers</span></div>
    <div class="stat"><b>{len(services)}</b><span>services</span></div>
    <div class="stat"><b>{e(lmap.get('backups', {}).get('repositories', '?'))}</b><span>restic repos</span></div>
    <div class="stat"><b>{e(lmap.get('backups', {}).get('drills', '?'))}</b><span>restore drills</span></div>
  </div>
</header>

<h2>The path a request takes</h2>
<div class="spine">
"""
    )
    for node in lmap.get("path") or []:
        parts.append(
            f'  <div class="node"><div class="k">{e(node["key"])}</div>'
            f'<div class="v">{e(node["title"])}</div>'
            f'<div class="s">{e(node.get("detail", ""))}</div></div>\n'
        )
    parts.append("</div>\n")
    if lmap.get("intro"):
        parts.append(f'<p class="lede" style="margin-top:18px;font-size:14px">{e(lmap["intro"])}</p>\n')

    parts.append("<h2>Domain → service → data</h2>\n")
    for gid in group_order:
        title = next(g["title"] for g in groups if g["id"] == gid)
        members = [s for s in services if s.get("group") == gid]
        if not members:
            continue
        parts.append(f'<div class="group"><h3>{e(title)}</h3>\n')
        parts.append(
            '<div class="row head"><div>domain</div><div>service</div><div>data</div></div>\n'
        )
        for svc in members:
            primary, rest = split_hosts(svc.get("domains") or [])
            host_html = (
                f'<div class="host">{e(primary)}'
                + (f'<small>{e(" · ".join(rest))}</small>' if rest else "")
                + "</div>"
            ) if primary else f'<div class="host" style="color:var(--muted)">— no public domain —</div>'
            containers = " · ".join(svc.get("containers") or [])
            parts.append(
                f'<div class="row">{host_html}'
                f'<div class="svc">{e(svc.get("name", svc["id"]))}<span class="cont">{e(containers)}</span></div>'
                f'<div class="data">{data_cell(svc)}</div></div>\n'
            )
        parts.append("</div>\n")

    parts.append("<h2>The data plane</h2>\n<div class=\"tiers\">\n")
    for name, tier in (lmap.get("tiers") or {}).items():
        servers = " · ".join(s["name"] for s in tier.get("servers") or [])
        items = []
        for server in tier.get("servers") or []:
            owned = [t for t in tier.get("tenants") or []]
            if owned:
                items.append(
                    f'<li>{e(server["engine"])} — {e(", ".join(owned))}</li>'
                )
                break
        backup = tier.get("backup") or {}
        if backup.get("kind") and backup["kind"] != "none":
            items.append(
                f'<li>backup — {e(backup["kind"])}'
                + (f', RPO {e(backup["rpo"])}' if backup.get("rpo") else "")
                + (f', RTO {e(backup["rto"])}' if backup.get("rto") else "")
                + "</li>"
            )
        else:
            items.append("<li>no backups — disposable by design</li>")
        parts.append(
            f'<div class="tier {e(name)}"><div class="t">{e(tier.get("title", name))}</div>'
            f'<div class="srv">{e(servers)}</div><ul>{"".join(items)}</ul>'
            + (f'<div class="note">{e(tier["notes"])}</div>' if tier.get("notes") else "")
            + "</div>\n"
        )

    retired = lmap.get("retired") or []
    if retired:
        items = "".join(
            f'<li><code>{e(r["name"])}</code> ({e(r["kind"])}) stopped {e(r.get("stopped", "?"))} — '
            f'delete on/after {e(r.get("delete_after", "?"))}, replaced by {e(r.get("replaced_by", ""))}</li>'
            for r in retired
        )
        parts.append(
            f'<div class="tier"><div class="t">retired (rollback, not service)</div>'
            f'<div class="srv">stopped containers, dated deletion</div><ul>{items}</ul></div>\n'
        )
    parts.append("</div>\n")

    infra = lmap.get("infrastructure") or []
    if infra:
        rows = "".join(
            f'<div class="row"><div class="host">{e(i["project"])}</div>'
            f'<div class="svc">{e(i["role"])}</div>'
            f'<div class="data">{e(", ".join(i.get("containers") or []))}</div></div>'
            for i in infra
        )
        parts.append(
            '<div class="group"><h3>Containers without a public domain</h3>'
            '<div class="row head"><div>project</div><div>role</div><div>containers</div></div>'
            f"{rows}</div>\n"
        )

    cards = lmap.get("cross_cutting") or []
    if cards:
        parts.append('<h2>Cross-cutting</h2>\n<div class="cards">\n')
        for card in cards:
            parts.append(
                f'<div class="card"><h3>{e(card["title"])}</h3><p>{e(card["body"])}</p></div>\n'
            )
        parts.append("</div>\n")

    rules = lmap.get("invariants") or []
    if rules:
        parts.append('<h2>Invariants worth knowing before changing anything</h2>\n<ol class="rules">\n')
        for rule in rules:
            parts.append(
                f'<li><b>{e(rule["title"])}</b>{e(rule["body"])}</li>\n'
            )
        parts.append("</ol>\n")

    parts.append(
        f'<div class="foot">servy.lehel.xyz · mariadb 13.0 · mongo 9.0 · rendered from '
        f'architecture/landscape.yaml · {e(lmap.get("as_of", ""))}</div>\n</div></body></html>\n'
    )
    return "".join(parts)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--map", type=Path, default=None, help="defaults to architecture/landscape.yaml")
    ap.add_argument(
        "--verify-host",
        action="append",
        default=[],
        metavar="HOST",
        help="also compare against the containers running on HOST (ssh; repeatable)",
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--html", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    repo = args.repo.resolve()
    map_path = args.map or (repo / "architecture" / "landscape.yaml")

    if args.selftest:
        derived = derive(repo, ["dns", "me"])
        domains = {d for v in derived.values() for d in v["domains"]}
        tiers = derive_tiers(repo)
        ok = len(derived) >= 30 and len(domains) >= 20 and len(tiers) >= 4
        print(
            f"selftest: {len(derived)} containers, {len(domains)} domains, "
            f"{len(tiers)} tiers -> {'ok' if ok else 'BROKEN'}"
        )
        return 0 if ok else 1

    if not map_path.exists():
        print(f"no map at {map_path}", file=sys.stderr)
        return 2
    raw = map_path.read_bytes()
    if raw.startswith(b"\x00GITCRYPT\x00"):
        print(
            f"{map_path} is encrypted and this checkout has no git-crypt key; "
            "use --map with a decrypted copy",
            file=sys.stderr,
        )
        return 2
    lmap = yaml.safe_load(raw) or {}

    if args.verify:
        problems, templated = verify(lmap, repo)
        for host in args.verify_host:
            problems += verify_live(lmap, derive_live(host), host)
        for problem in problems:
            print(f"  drift: {problem}")
        if problems:
            print(f"\n{len(problems)} problem(s). Fix the map (--build prints the current values) or the repo.")
            return 1
        services = len(lmap.get("services") or [])
        extra = f", {len(set(templated))} with rendered domains" if templated else ""
        print(
            f"ok: {services} services, {len(lmap.get('tiers') or {})} tiers agree "
            f"with the repository{extra}"
        )
        return 0

    if args.build:
        print(build(lmap, repo))
        return 0

    print(render_html(lmap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
