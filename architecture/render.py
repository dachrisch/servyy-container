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
    """Ask a host what its containers actually serve, and what they reach.

    The compose files in this repository render most hostnames from `${SERVICE_HOST}`
    at deploy time, so their text cannot verify anything — but `docker inspect` on
    the host can. The same inspect is the only honest source for the dependency
    edges: an app's env names its database tier, or the app sits on the tier's
    network. Requires ssh access; CI does not have it, humans do.
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
        live[name] = {
            "domains": domains,
            "env": "\n".join(item["Config"].get("Env") or []),
            "networks": set((item.get("NetworkSettings") or {}).get("Networks") or {}),
        }
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
# dependencies
# --------------------------------------------------------------------------- #
DATA_KINDS = {"mariadb", "mongo"}


def server_tiers(lmap: dict[str, Any]) -> dict[str, str]:
    """server name -> tier name, from the map's own tiers section."""
    return {
        server["name"]: name
        for name, tier in (lmap.get("tiers") or {}).items()
        for server in tier.get("servers") or []
    }


def dependencies(lmap: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge the map declares, resolved once for both the check and the view.

    Three kinds, and only three: `data` (a service to its tier server), `call`
    (a service to a service, an infrastructure container, or a tier server) and
    `external` (a service out of the building). A target that resolves to nothing
    is not an edge, it is a typo — `verify_edges` says so.
    """
    tiers = server_tiers(lmap)
    edges: list[dict[str, Any]] = []
    for svc in lmap.get("services") or []:
        data = svc.get("data") or {}
        if data.get("kind") in DATA_KINDS and data.get("server"):
            edges.append(
                {"src": svc["id"], "dst": data["server"], "kind": "data",
                 "tier": tiers.get(data["server"])}
            )
        for target in svc.get("calls") or []:
            if target.startswith("external:"):
                edges.append(
                    {"src": svc["id"], "dst": target, "kind": "external",
                     "external": target.split(":", 1)[1]}
                )
            else:
                edges.append({"src": svc["id"], "dst": target, "kind": "call"})
    return edges


def outward_evidence(repo: Path, lmap: dict[str, Any]) -> dict[str, set[str]]:
    """project -> the externals its own source text mentions.

    The repository is the static half of the check: a compose file or an ansible
    env template that names the external's `check:` key (or its `via:` host) is
    evidence that the project depends on it. `--verify-host` is the other half.
    """
    externals = {x["id"]: x for x in lmap.get("externals") or []}
    sources: list[tuple[str, Path]] = [(p.parent.name, p) for p in compose_files(repo)]
    templates = repo / "ansible" / "plays" / "roles" / "docker_service" / "templates"
    if templates.is_dir():
        for entry in sorted(templates.iterdir()):
            if entry.is_dir():
                sources += [(entry.name, f) for f in sorted(entry.rglob("*.j2"))]
            elif entry.suffix == ".j2":
                sources.append((entry.name.split(".")[0], entry))
    found: dict[str, set[str]] = {}
    for project, path in sources:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for xid, external in externals.items():
            keys = [str(external.get("check") or "")]
            if external.get("via"):
                keys.append(str(external["via"]).replace("*", ""))
            if any(key and key in text for key in keys):
                found.setdefault(project, set()).add(xid)
    return found


def verify_edges(lmap: dict[str, Any], repo: Path) -> list[str]:
    """Check every edge against the repository, in both directions.

    A data edge is checked against the tenant inventory (server, tier, database
    and — for MariaDB — user); a call is checked for resolving to something that
    exists; an outward edge is checked against the project's own compose file and
    env template, so a new app that starts calling opencode cannot go unlisted,
    and a listed edge cannot outlive the env that justified it.
    """
    problems: list[str] = []
    services = {s["id"]: s for s in lmap.get("services") or []}
    infra = {
        container
        for entry in lmap.get("infrastructure") or []
        for container in entry.get("containers") or []
    }
    containers_of = {
        container for svc in services.values() for container in svc.get("containers") or []
    }
    externals = {x["id"] for x in lmap.get("externals") or []}
    tiers = server_tiers(lmap)
    rows = {
        row.get("tenant"): row
        for row in (load_yaml(repo / "ansible" / "plays" / "vars" / "db_tenants.yml") or {}).get(
            "db_tenants"
        )
        or []
    }

    for svc in lmap.get("services") or []:
        data = svc.get("data") or {}
        if data.get("kind") not in DATA_KINDS:
            continue
        tenant = data.get("tenant")
        if not tenant:
            problems.append(
                f"{svc['id']}: data has no tenant — the edge cannot be checked against db_tenants.yml"
            )
            continue
        row = rows.get(tenant)
        if row is None:
            problems.append(f"{svc['id']}: tenant {tenant} has no row in db_tenants.yml")
            continue
        if row.get("server") != data.get("server"):
            problems.append(
                f"{svc['id']}: map puts tenant {tenant} on {data.get('server')}, "
                f"the inventory on {row.get('server')}"
            )
        if data.get("db") and row.get("db") and data["db"] != row["db"]:
            problems.append(
                f"{svc['id']}: map says database {data['db']}, the inventory says {row['db']}"
            )
        # MariaDB accounts are asserted by roles/db_tier; Mongo accounts are not
        # (the inventory's dontforget user differs from the live dontforget_app),
        # so comparing them would answer a question this check cannot ask.
        if (
            row.get("engine") == "mariadb"
            and data.get("user")
            and row.get("user")
            and data["user"] != row["user"]
        ):
            problems.append(
                f"{svc['id']}: map says user {data['user']}, the inventory says {row['user']}"
            )
        tier = tiers.get(data.get("server"))
        if tier and row.get("tier") and tier != row["tier"]:
            problems.append(
                f"{svc['id']}: tenant {tenant} sits in the {tier} tier in the map, "
                f"{row['tier']} in the inventory"
            )

    for svc in lmap.get("services") or []:
        for target in svc.get("calls") or []:
            if target.startswith("external:"):
                if target.split(":", 1)[1] not in externals:
                    problems.append(f"{svc['id']}: calls {target}, which is not in externals[]")
            elif (
                target not in services
                and target not in containers_of
                and target not in infra
                and target not in tiers
            ):
                problems.append(
                    f"{svc['id']}: calls {target}, which is not a service, a container "
                    "or a tier server"
                )

    for row in lmap.get("control") or []:
        for side in ("from", "to"):
            name = row.get(side)
            if not name or name == "*":
                continue
            if (
                name not in services
                and name not in containers_of
                and name not in infra
                and name not in tiers
            ):
                problems.append(f"control: {name} resolves to nothing")

    ignore = set(lmap.get("ignore_projects") or [])
    evidence = outward_evidence(repo, lmap)
    claimed: dict[str, set[str]] = {}
    for svc in lmap.get("services") or []:
        for target in svc.get("calls") or []:
            if target.startswith("external:"):
                claimed.setdefault(svc.get("project"), set()).add(target.split(":", 1)[1])
    for project, ids in sorted(evidence.items()):
        if project in ignore:
            continue
        for xid in sorted(ids - claimed.get(project, set())):
            owners = [s["id"] for s in lmap.get("services") or [] if s.get("project") == project]
            who = "/".join(owners) or "no service"
            problems.append(
                f"{project}: its source names external {xid}, but {who} in the map "
                "does not claim it"
            )
    for project, ids in sorted((p, i) for p, i in claimed.items() if p):
        if project in ignore:
            continue
        mine = [s for s in lmap.get("services") or [] if s.get("project") == project]
        if mine and all(s.get("external_compose") for s in mine):
            continue  # the stack's env lives in the app's own repository
        for xid in sorted(ids - evidence.get(project, set())):
            problems.append(
                f"{project}: the map claims external {xid}, but nothing in its compose "
                "file or env template names it"
            )

    return problems


def verify_live_edges(
    lmap: dict[str, Any], live: dict[str, dict[str, Any]], host: str
) -> list[str]:
    """Check each declared edge against the container that has to carry it.

    A data edge is real when the env names the server or the container sits on the
    tier's network (Queen proves the second branch is needed: no env names its
    mongo). An outward edge is real when the env carries the external's `check:` key
    or names its host. Aggregates are all the poster shows, so this is the proof.
    """
    problems: list[str] = []
    externals = {x["id"]: x for x in lmap.get("externals") or []}
    for svc in lmap.get("services") or []:
        if svc.get("host", "servy.lehel.xyz") != host:
            continue
        entries = [live[c] for c in svc.get("containers") or [] if c in live]
        if not entries:
            continue
        env = "\n".join(entry["env"] for entry in entries)
        networks: set[str] = set()
        for entry in entries:
            networks |= entry["networks"]
        data = svc.get("data") or {}
        if data.get("kind") in DATA_KINDS and data.get("server"):
            server = data["server"]
            token = server.split(".")[0].replace("-", "_")
            if server not in env and not any(token in network for network in networks):
                problems.append(
                    f"{svc['id']}: map says it reads {server}, but no container on {host} "
                    f"names it and none sits on a {token} network"
                )
        for target in svc.get("calls") or []:
            if not target.startswith("external:"):
                continue
            xid = target.split(":", 1)[1]
            external = externals.get(xid) or {}
            key = str(external.get("check") or "")
            via = str(external.get("via") or "").replace("*", "")
            if key and key not in env and via and via not in env:
                problems.append(
                    f"{svc['id']}: map says it calls {external.get('title', xid)}, but no "
                    f"container on {host} sets {key} or names {via}"
                )
    return problems


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
  .lane{display:grid;grid-template-columns:88px minmax(0,1fr);border:1px solid var(--ink);
    background:var(--card);box-shadow:5px 5px 0 rgba(22,23,15,.08);margin-bottom:10px}
  .lane-k{padding:12px;border-right:1px solid var(--rule);display:flex;align-items:flex-start;
    justify-content:flex-end;text-align:right;font-family:"IBM Plex Mono",monospace;font-size:9px;
    letter-spacing:.14em;text-transform:uppercase;color:var(--muted);line-height:1.5}
  .lane-body{padding:12px 14px 11px;min-width:0}
  .lane-flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:7px}
  .lane-flow.inward{display:grid;grid-template-columns:auto auto repeat(4,minmax(0,1fr));
    align-items:stretch}
  .lane-flow.control{align-items:flex-start}
  .lane-flow+.lane-flow{margin-top:7px}
  .node{border:1px solid var(--rule);background:var(--paper);padding:6px 9px;min-width:0}
  .node h4{margin:0;font-size:12px;font-weight:700;letter-spacing:-.01em}
  .node h4.big{font-family:"Instrument Serif",serif;font-size:18px;font-weight:400;line-height:1.1}
  .node p{margin:3px 0 0;font-size:10.5px;line-height:1.4;color:#3c3d31}
  .node .mono{font-family:"IBM Plex Mono",monospace;font-size:9.5px;color:var(--muted);
    display:block;margin-top:3px}
  .node .mono.muted{color:#8d8778;margin-top:1px}
  .node.tier{border-left:3px solid var(--rule)}
  .node.tier.high{border-left-color:var(--high)}
  .node.tier.nonprod{border-left-color:var(--nonprod)}
  .node.tier.business{border-left-color:var(--business)}
  .node.tier.private{border-left-color:var(--private)}
  .node.dashed{border-style:dashed}
  .flow-arrow{display:flex;align-items:center;gap:5px;font-family:"IBM Plex Mono",monospace;
    font-size:13px;color:var(--muted);padding:0 3px}
  .flow-arrow em{font-style:normal;font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;
    color:var(--muted);white-space:nowrap}
  .lane-note{margin:9px 0 0;font-size:11px;line-height:1.45;color:var(--muted)}
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
  @media(max-width:1080px){ .hosts{grid-template-columns:1fr 1fr} .connectors{display:none}
    .lane-flow.inward{grid-template-columns:auto auto 1fr 1fr} }
  @media(max-width:820px){
    .mast-body{grid-template-columns:1fr}
    .edge{grid-template-columns:1fr}
    .arrow{display:none}
    .hosts{grid-template-columns:1fr}
    .foundation{grid-template-columns:1fr}
    .lane{grid-template-columns:1fr}
    .lane-k{border-right:0;border-bottom:1px solid var(--rule);
      justify-content:flex-start;text-align:left}
    .lane-flow.inward{grid-template-columns:1fr}
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


def render_dependencies(lmap: dict[str, Any], edges: list[dict[str, Any]]) -> str:
    """The dependency section: three lanes, aggregates only.

    The poster shows shape, not one arrow per app: the per-edge proof is `--verify`,
    which is why every count here comes from the same `dependencies()` the check
    uses. A number on this page the verifier cannot reproduce is a decoration.
    """
    tiers = lmap.get("tiers") or {}
    services = lmap.get("services") or []
    externals = {x["id"]: x for x in lmap.get("externals") or []}

    consumers: dict[str, list[str]] = {}
    for edge in edges:
        if edge["kind"] == "data" and edge.get("tier"):
            consumers.setdefault(edge["tier"], []).append(edge["src"])
    data_edges = sum(len(members) for members in consumers.values())
    tenant_count = sum(len(tier.get("tenants") or []) for tier in tiers.values())

    def arrow(label: str = "") -> str:
        em = "<em>%s</em>" % e(label) if label else ""
        return '<div class="flow-arrow">%s&#8594;</div>' % em

    def node(
        title: str,
        body: str = "",
        mono: str = "",
        cls: str = "",
        big: bool = False,
        sub: str = "",
    ) -> str:
        head = "<h4%s>%s</h4>" % (' class="big"' if big else "", e(title))
        extra = "<p>%s</p>" % e(body) if body else ""
        tail = '<span class="mono">%s</span>' % e(mono) if mono else ""
        more = '<span class="mono muted">%s</span>' % e(sub) if sub else ""
        return '<div class="node %s">%s%s%s%s</div>' % (cls.strip(), head, extra, tail, more)

    def disp(name: str) -> str:
        for svc in services:
            if name == svc["id"] or name in (svc.get("containers") or []):
                return svc.get("name", name)
        if "." in name:
            kind = name.split(".", 1)[1].replace("-", " ").replace("_", " ")
            return kind[:1].upper() + kind[1:]
        return name

    def plural(count: int, word: str) -> str:
        return "%d %s%s" % (count, word, "" if count == 1 else "s")

    clusters = {svc.get("cluster") or svc.get("group") for svc in services}
    inward = [
        node(plural(len(services), "service"), "on servy, in %d clusters" % len(clusters),
             "servy.lehel.xyz", big=True),
        arrow("read"),
    ]
    for name, tier in tiers.items():
        members = consumers.get(name) or []
        names = tier.get("tenants") or []
        inward.append(
            node(
                name,
                "%s · %s" % (plural(len(members), "app"), plural(len(names), "tenant")),
                " · ".join(s["name"] for s in tier.get("servers") or []),
                "tier " + name,
                sub=", ".join(names),
            )
        )
    inward_note = (
        "%s read %s, each through its own user — none root, and no tenant reaches "
        "another's database. The arrow is a docker network plus a hostname: the app "
        "holds no credential beyond its own row." % (plural(data_edges, "service"), plural(tenant_count, "tenant"))
    )

    opencode = externals.get("opencode") or {}
    outward_apps = [
        edge["src"] for edge in edges
        if edge["kind"] == "external" and edge.get("external") == "opencode"
    ]
    app_names = ", ".join(sorted(disp(sid) for sid in outward_apps)) or "none"
    gate = next(
        (
            container
            for entry in lmap.get("infrastructure") or []
            if entry.get("project") == "opencode-authgate"
            for container in entry.get("containers") or []
        ),
        "opencode-authgate.authgate",
    )
    upstream = next((s.get("name", "") for s in services if s["id"] == "codey-opencode"), "OpenCode")
    outward = [
        node(plural(len(outward_apps), "app"), app_names, "", big=True),
        arrow("X-Api-Key"),
        node(str(opencode.get("via") or "code.lehel.xyz"), "Traefik on codey — one API-key router",
             str(opencode.get("host") or "")),
        arrow(),
        node(gate.split(".", 1)[-1], str(opencode.get("auth") or "").split(" — ")[0] or "key → Basic",
             "caddy · forwardAuth"),
        arrow(),
        node(upstream, "no database, no tier", str(opencode.get("host") or "")),
    ]
    atlas = externals.get("atlas") or {}
    atlas_apps = sorted(
        disp(edge["src"]) for edge in edges
        if edge["kind"] == "external" and edge.get("external") == "atlas"
    )
    outward_note = (
        "Outward is one door: the API key stops at the gate, which holds the Basic "
        "credential, so no app ever carries the server password."
    )
    if atlas:
        outward_note += (
            " %s keep their data in %s — outside every tier, so no restic repo of "
            "ours covers it." % (", ".join(atlas_apps) or "Two apps", atlas.get("title", "Atlas"))
        )

    control_rows = []
    for row in lmap.get("control") or []:
        src = disp(str(row.get("from") or ""))
        label = str(row.get("label") or "")
        if str(row.get("to")) == "*":
            target = node("every container", label)
        else:
            target = node(disp(str(row.get("to"))), label)
        control_rows.append(
            '<div class="lane-flow">%s%s%s</div>' % (node(src), arrow(), target)
        )
    control_note = (
        "Control crosses the same machine boundary: the Portainer on servy drives the "
        "agent on codey, and the schedulers run on both hosts."
    )

    body = "".join(
        '<div class="lane"><div class="lane-k">%s</div><div class="lane-body">'
        '<div class="lane-flow %s">%s</div><p class="lane-note">%s</p></div></div>\n'
        % (e(kind), e(kind), "".join(flow), e(note))
        for kind, flow, note in (
            ("inward", inward, inward_note),
            ("outward", outward, outward_note),
            ("control", control_rows, control_note),
        )
    )
    return (
        '  <div class="sec-head"><span class="sec-num">3</span><h2>What reaches what</h2>'
        '<span class="sub">three lanes, every edge checked against the repo and the host</span>'
        '<span class="rule"></span></div>\n' + body
    )


def render_html(lmap: dict[str, Any]) -> str:
    tiers = lmap.get("tiers") or {}
    hosts = lmap.get("hosts") or [{"name": "servy.lehel.xyz", "role": "production"}]
    services = lmap.get("services") or []
    domains = sorted({d for s in services for d in (s.get("domains") or [])})
    groups = {g["id"]: g["title"] for g in lmap.get("groups") or []}
    total_containers = sum(int(h.get("containers") or 0) for h in hosts)
    backups = lmap.get("backups") or {}
    edges = dependencies(lmap)
    outward = sum(
        1 for edge in edges if edge["kind"] == "external" and edge.get("external") == "opencode"
    )

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
        ("dependency edges", str(len(edges)), "checked, not asserted"),
        ("database tiers", str(len(tiers)), "mariadb 13.0 · mongo 9.0"),
        ("apps → codey", str(outward), "one door, one key"),
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
    out.append(render_dependencies(lmap, edges))

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
            "4", "The foundation",
            "the parts that make three machines behave like one system",
            lmap.get("foundation") or [],
        )
    )
    out.append(
        cards_section("5", "Invariants", "each one was learned by breaking it", lmap.get("invariants") or [])
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
        problems += verify_edges(lmap, repo)
        for host in args.verify_host:
            live = derive_live(host)
            problems += verify_live(lmap, live, host)
            problems += verify_live_edges(lmap, live, host)
        for problem in problems:
            print(f"  drift: {problem}")
        if problems:
            print(f"\n{len(problems)} problem(s). Fix the map (--build prints the current values) or the repo.")
            return 1
        services = len(lmap.get("services") or [])
        edges = len(dependencies(lmap))
        extra = f", {len(set(templated))} with rendered domains" if templated else ""
        print(
            f"ok: {services} services, {edges} dependency edges, "
            f"{len(lmap.get('tiers') or {})} tiers agree with the repository{extra}"
        )
        return 0

    if args.build:
        print(build(lmap, repo))
        return 0

    print(render_html(lmap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
