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

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment, not logic
    raise SystemExit(
        "render.py needs PyYAML. The ansible interpreter has it:\n"
        "  /home/cda/.pyenv/versions/servy-ansible/bin/python3 architecture/render.py --verify\n"
        "or: python3 -m pip install pyyaml"
    )

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
  *,*::before,*::after{box-sizing:border-box}
  :root{
    --paper:#f1eee6; --card:#f8f6f0; --ink:#16170f; --muted:#5f5b4c; --rule:#d2ccbb;
    --servy:#a8460a; --codey:#0d6b62; --test:#6b4a9b;
    --high:#6d5efc; --nonprod:#d98324; --business:#0f8b8d; --private:#b3446c; --ext:#6b7280;
  }
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:"Bricolage Grotesque",system-ui,-apple-system,sans-serif;
    font-optical-sizing:auto;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
    background-image:
      repeating-linear-gradient(to right,rgba(22,23,15,.05) 0 1px,transparent 1px 92px),
      repeating-linear-gradient(to bottom,rgba(22,23,15,.05) 0 1px,transparent 1px 92px);
    -webkit-mask-image:linear-gradient(to bottom,rgba(0,0,0,.9),rgba(0,0,0,.25));
    mask-image:linear-gradient(to bottom,rgba(0,0,0,.9),rgba(0,0,0,.25))}
  .poster{position:relative;z-index:1;max-width:1540px;margin:0 auto;
    padding:clamp(24px,3.4vw,52px) clamp(16px,4vw,56px) 64px}
  .mast-top{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
    font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--muted);padding-bottom:12px;border-bottom:1px solid var(--ink)}
  .mast-top span:nth-child(2){flex:1;text-align:center;min-width:200px}
  h1{font-family:"Instrument Serif",Georgia,serif;font-weight:400;
    font-size:clamp(44px,7vw,100px);line-height:.94;letter-spacing:-.015em;
    margin:clamp(22px,3vw,40px) 0 0}
  h1 em{font-style:italic;color:var(--servy)}
  .mast-body{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);
    gap:clamp(24px,4vw,64px);align-items:end;margin-top:clamp(18px,2.4vw,30px)}
  .lede{margin:0;font-size:clamp(15px,1.35vw,18px);line-height:1.5;max-width:56ch;color:#2b2c22}
  .stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 22px;margin:0}
  .stat{border-top:1px solid var(--ink);padding-top:8px}
  .stat dt{font-family:"IBM Plex Mono",monospace;font-size:9.5px;letter-spacing:.13em;
    text-transform:uppercase;color:var(--muted)}
  .stat dd{margin:2px 0 0;font-family:"Instrument Serif",serif;font-size:clamp(24px,2.4vw,34px);line-height:1}
  .stat dd small{font-family:"Bricolage Grotesque",sans-serif;font-size:11px;color:var(--muted);
    display:block;margin-top:5px}
  .sec-head{display:flex;align-items:baseline;gap:14px;margin:clamp(34px,4.6vw,60px) 0 14px}
  .sec-num{font-family:"Instrument Serif",serif;font-style:italic;font-size:22px;color:var(--servy);line-height:1}
  .sec-head h2{margin:0;font-size:clamp(17px,1.6vw,21px);font-weight:700;letter-spacing:-.01em}
  .sec-head .sub{font-size:12.5px;color:var(--muted)}
  .sec-head .rule{flex:1;height:1px;background:var(--rule)}
  .edge{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto 1fr;align-items:stretch;gap:10px;
    border:1px solid var(--ink);background:var(--card);box-shadow:5px 5px 0 rgba(22,23,15,.08)}
  .step{padding:13px 15px 14px;min-width:0}
  .step .k{font-family:"IBM Plex Mono",monospace;font-size:9px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--muted);display:block;margin-bottom:3px}
  .step h3{margin:0;font-size:15px;font-weight:700;letter-spacing:-.01em}
  .step p{margin:5px 0 0;font-size:11.5px;line-height:1.45;color:#3c3d31}
  .step .mono{font-family:"IBM Plex Mono",monospace;font-size:10.5px;margin-top:6px;color:var(--muted)}
  .arrow{display:flex;align-items:center;justify-content:center;color:var(--muted);
    font-family:"IBM Plex Mono",monospace;font-size:15px;padding:0 2px}
  .connectors{display:grid;grid-template-columns:1.45fr 1fr 1fr;gap:20px;height:26px}
  .connectors span{width:1px;height:100%;margin:0 auto;
    background:repeating-linear-gradient(to bottom,var(--rule) 0 4px,transparent 4px 9px)}
  .hosts{display:grid;grid-template-columns:1.45fr 1fr 1fr;gap:20px;align-items:start}
  .host{border:1px solid var(--ink);background:var(--card);box-shadow:5px 5px 0 rgba(22,23,15,.08)}
  .host-head{padding:12px 14px 11px;border-bottom:1px solid var(--rule)}
  .host-head.servy{border-top:4px solid var(--servy)}
  .host-head.codey{border-top:4px solid var(--codey)}
  .host-head.test{border-top:4px solid var(--test)}
  .host-name{font-family:"Instrument Serif",serif;font-size:22px;line-height:1.05;margin:0;font-weight:400}
  .host-role{font-family:"IBM Plex Mono",monospace;font-size:9.5px;letter-spacing:.13em;
    text-transform:uppercase;color:var(--muted);margin-top:4px}
  .host-tag{font-size:11.5px;color:#3c3d31;margin-top:6px}
  .specs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 12px;
    padding:10px 14px;border-bottom:1px solid var(--rule);background:rgba(22,23,15,.02)}
  .spec{font-family:"IBM Plex Mono",monospace;font-size:9px;letter-spacing:.08em;
    text-transform:uppercase;color:var(--muted)}
  .spec b{display:block;color:var(--ink);font-size:11.5px;font-weight:500;
    text-transform:none;letter-spacing:0;margin-top:2px}
  .clusters{padding:12px 14px 14px}
  .cluster{margin-bottom:12px}
  .cluster:last-child{margin-bottom:0}
  .cluster .h{font-family:"IBM Plex Mono",monospace;font-size:9px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--muted);margin-bottom:6px;display:flex;gap:6px;align-items:baseline}
  .cluster .h .n{color:#b3ad9c}
  .chips{display:flex;flex-wrap:wrap;gap:5px}
  .chip{display:inline-flex;align-items:baseline;gap:6px;border:1px solid var(--rule);
    background:var(--paper);padding:3px 7px;font-size:11px;line-height:1.3}
  .chip em{font-family:"IBM Plex Mono",monospace;font-style:normal;font-size:9.5px;color:var(--muted)}
  .dot{width:6px;height:6px;border-radius:50%;background:var(--rule);flex:0 0 auto;transform:translateY(-1px)}
  .d-high{background:var(--high)} .d-nonprod{background:var(--nonprod)}
  .d-business{background:var(--business)} .d-private{background:var(--private)}
  .d-ext{background:var(--ext)} .d-none{background:#c9c4b4}
  .host-foot{padding:9px 14px;border-top:1px solid var(--rule);font-family:"IBM Plex Mono",monospace;
    font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .foundation{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .f-card{border:1px solid var(--ink);background:var(--card);padding:13px 15px;box-shadow:4px 4px 0 rgba(22,23,15,.06)}
  .f-card h3{margin:0 0 5px;font-size:14px;font-weight:700}
  .f-card p{margin:0;font-size:12px;line-height:1.5;color:#3c3d31}
  .foot{margin-top:clamp(32px,4vw,56px);padding-top:14px;border-top:1px solid var(--ink);
    display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
    font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.1em;
    text-transform:uppercase;color:var(--muted)}
  .legend{display:flex;gap:14px;flex-wrap:wrap}
  .legend span{display:inline-flex;align-items:baseline;gap:5px}
  @media(max-width:1080px){ .hosts{grid-template-columns:1fr 1fr} .connectors{display:none} }
  @media(max-width:820px){
    .mast-body{grid-template-columns:1fr}
    .edge{grid-template-columns:1fr}
    .arrow{display:none}
    .hosts{grid-template-columns:1fr}
    .foundation{grid-template-columns:1fr}
  }
"""

TIER_DOT = {"high": "d-high", "nonprod": "d-nonprod", "business": "d-business", "private": "d-private"}
HOST_CLASS = {"servy.lehel.xyz": "servy", "codey.lehel.xyz": "codey", "servyy-test.lxd": "test"}


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def service_tier(svc: dict[str, Any], tiers: dict[str, Any]) -> str | None:
    server = (svc.get("data") or {}).get("server")
    for name, tier in tiers.items():
        if server in {s["name"] for s in tier.get("servers", [])}:
            return name
    if (svc.get("data") or {}).get("kind") == "external":
        return "ext"
    return None


def service_domain(svc: dict[str, Any]) -> str:
    domains = svc.get("domains") or []
    if not domains:
        return ""
    return min(domains, key=lambda d: (d.startswith("www."), len(d)))


def service_chip(svc: dict[str, Any], tiers: dict[str, Any]) -> str:
    tier = service_tier(svc, tiers)
    dot = '<span class="dot d-%s"></span>' % (tier or "none")
    domain = service_domain(svc)
    tail = ("<em>%s</em>" % e(domain)) if domain else ""
    return '<span class="chip">%s%s%s</span>' % (dot, e(svc.get("name", svc["id"])), tail)


def tier_chip(name: str, tier: dict[str, Any]) -> str:
    servers = " · ".join(s["name"] for s in tier.get("servers", []))
    return '<span class="chip"><span class="dot d-%s"></span>%s</span>' % (e(name), e(servers))


def render_html(lmap: dict[str, Any]) -> str:
    tiers = lmap.get("tiers") or {}
    hosts = lmap.get("hosts") or [{"name": "servy.lehel.xyz", "role": "production"}]
    services = lmap.get("services") or []
    domains = sorted({d for s in services for d in (s.get("domains") or [])})
    groups = {g["id"]: g["title"] for g in lmap.get("groups") or []}
    total_containers = sum(int(h.get("containers") or 0) for h in hosts)
    backups = lmap.get("backups") or {}

    title = e(lmap.get("title", "Three machines, one edge."))
    if "one edge" in title:
        title = title.replace("one edge", "<em>one edge</em>", 1)

    out: list[str] = []
    out.append(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n"
        "<link href=\"https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,700;12..96,800&family=IBM+Plex+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&display=swap\" rel=\"stylesheet\">\n"
        "<style>" + CSS + "</style>\n</head>\n<body>\n<div class=\"poster\">\n"
    )
    out.append(
        '  <div class="mast-top"><span>%s</span><span>%s</span>'
        '<span>service landscape</span></div>\n'
        % (e(lmap.get("as_of", "")), " · ".join(e(h["name"]) for h in hosts))
    )
    out.append("  <h1>%s</h1>\n" % title)
    out.append(
        '  <div class="mast-body">\n    <p class="lede">%s</p>\n    <dl class="stats">\n'
        % e(lmap.get("subtitle", ""))
    )
    for label, value, small in (
        ("containers", str(total_containers), "across %d machines" % len(hosts)),
        ("public hostnames", str(len(domains)), "one router each"),
        ("database tiers", str(len(tiers)), "mariadb 13.0 · mongo 9.0"),
        ("restic repos", str(backups.get("repositories", "?")), str(backups.get("drills", ""))),
    ):
        out.append(
            '      <div class="stat"><dt>%s</dt><dd>%s<small>%s</small></dd></div>\n'
            % (e(label), e(value), e(small))
        )
    out.append("    </dl>\n  </div>\n")

    edge = lmap.get("edge") or []
    if edge:
        out.append(
            '  <div class="sec-head"><span class="sec-num">1</span><h2>The edge</h2>'
            '<span class="sub">nothing reaches a container without passing here</span>'
            '<span class="rule"></span></div>\n  <div class="edge">\n'
        )
        for index, step in enumerate(edge):
            if index:
                out.append('    <div class="arrow">&#8594;</div>\n')
            mono = '<div class="mono">%s</div>' % e(step["mono"]) if step.get("mono") else ""
            out.append(
                '    <div class="step"><span class="k">%s</span><h3>%s</h3><p>%s</p>%s</div>\n'
                % (e(step.get("k", "")), e(step.get("title", "")), e(step.get("body", "")), mono)
            )
        out.append("  </div>\n")

    out.append(
        '  <div class="sec-head"><span class="sec-num">2</span><h2>Three machines</h2>'
        '<span class="sub">who runs what, and which tier each service reads</span>'
        '<span class="rule"></span></div>\n'
        '  <div class="connectors"><span></span><span></span><span></span></div>\n'
        '  <div class="hosts">\n'
    )
    for host in hosts:
        name = host["name"]
        cls = HOST_CLASS.get(name, "servy")
        specs = host.get("specs") or {}
        out.append('    <div class="host">\n')
        out.append('      <div class="host-head %s">\n' % cls)
        out.append('        <h3 class="host-name">%s</h3>\n' % e(name))
        out.append('        <div class="host-role">%s</div>\n' % e(host.get("role", "")))
        out.append('        <div class="host-tag">%s</div>\n' % e(host.get("tagline", "")))
        out.append("      </div>\n      <div class=\"specs\">\n")
        for key in ("cpu", "mem", "disk", "os"):
            out.append(
                '        <div class="spec">%s<b>%s</b></div>\n'
                % (e({"cpu": "cpu", "mem": "memory", "disk": "disk", "os": "os"}[key]), e(specs.get(key, "—")))
            )
        out.append('      </div>\n      <div class="clusters">\n')

        mine = [s for s in services if s.get("host", "servy.lehel.xyz") == name]
        clusters: dict[str, list[dict[str, Any]]] = {}
        for svc in mine:
            key = svc.get("cluster") or groups.get(svc.get("group"), svc.get("group") or "Other")
            clusters.setdefault(key, []).append(svc)
        if name == "servy.lehel.xyz":
            clusters["Data tier"] = []
        if not clusters:
            out.append(
                '        <div class="cluster"><div class="h">no services of its own</div>'
                '<div class="chips"><span class="chip">the same compose files, deployed for '
                "testing before production</span></div></div>\n"
            )
        def cluster_rank(item: tuple[str, list]) -> tuple[int, str]:
            name_ = item[0]
            if name_ == "Edge":
                return (0, name_)
            if name_ == "Data tier":
                return (9, name_)
            order_ = list(groups.values())
            return (1 + order_.index(name_) if name_ in order_ else 8, name_)

        for cluster_name, members in sorted(clusters.items(), key=cluster_rank):
            count = len(tiers) if cluster_name == "Data tier" else len(members)
            out.append(
                '        <div class="cluster"><div class="h">%s<span class="n">%d</span></div>'
                '<div class="chips">' % (e(cluster_name), count)
            )
            if cluster_name == "Data tier":
                out.append("".join(tier_chip(n, t) for n, t in tiers.items()))
            else:
                out.append("".join(service_chip(svc, tiers) for svc in members))
            out.append("</div></div>\n")
        out.append("      </div>\n")
        out.append(
            '      <div class="host-foot">%s containers</div>\n    </div>\n'
            % e(host.get("containers", "?"))
        )
    out.append("  </div>\n")

    def cards_section(number: str, heading: str, sub: str, cards: list[dict[str, Any]]) -> str:
        if not cards:
            return ""
        body = "".join(
            '    <div class="f-card"><h3>%s</h3><p>%s</p></div>\n'
            % (e(card["title"]), e(card["body"]))
            for card in cards
        )
        return (
            '  <div class="sec-head"><span class="sec-num">%s</span><h2>%s</h2>'
            '<span class="sub">%s</span><span class="rule"></span></div>\n'
            '  <div class="foundation">\n%s  </div>\n' % (number, e(heading), e(sub), body)
        )

    out.append(
        cards_section(
            "3", "The foundation",
            "the parts that make three machines behave like one system",
            lmap.get("foundation") or [],
        )
    )
    out.append(
        cards_section("4", "Invariants", "each one was learned by breaking it", lmap.get("invariants") or [])
    )

    legend = "".join(
        '<span><span class="dot d-%s"></span>%s</span>' % (k, k)
        for k in ("high", "nonprod", "business", "private", "ext")
    )
    out.append(
        '  <div class="foot"><span>rendered from architecture/landscape.yaml</span>'
        '<span class="legend">%s</span><span>%s</span></div>\n</div>\n</body>\n</html>\n'
        % (legend, e(lmap.get("as_of", "")))
    )
    return "".join(out)

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
        # The map may be ciphertext here (CI has no key); the ignore list is
        # therefore a constant, and --verify is what checks the map knows it.
        derived = derive(repo, ["dns", "me", "devhub", "platzler-heid", "thore"])
        resolved = {d for v in derived.values() for d in v["domains"]}
        public = [c for c, v in derived.items() if v["domains"] or v["templated"]]
        tiers = derive_tiers(repo)
        # Most services render their host from ${SERVICE_HOST}, so the compose TEXT
        # yields few literal domains: count PUBLIC containers, not literal hosts.
        ok = len(derived) >= 30 and len(public) >= 20 and len(tiers) >= 4
        print(
            f"selftest: {len(derived)} containers ({len(public)} public, "
            f"{len(resolved)} with literal domains), {len(tiers)} tiers "
            f"-> {'ok' if ok else 'BROKEN'}"
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
