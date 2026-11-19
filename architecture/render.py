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


SOCKET = "docker:socket"


def mounts_socket(source: str) -> bool:
    """A bind of the Docker socket itself, or of the /var/run that holds it."""
    return source.rstrip("/") in {"/var/run/docker.sock", "/var/run", "/run/docker.sock", "/run"}


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
                 "domains": set(), "templated": False, "socket": False},
            )
            entry["domains"] |= domains
            entry["socket"] = entry["socket"] or any(
                mounts_socket(str(v.get("source", "") if isinstance(v, dict) else v).split(":", 1)[0])
                for v in cfg.get("volumes") or []
            )
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
        command = (item["Config"].get("Entrypoint") or []) + (item["Config"].get("Cmd") or [])
        live[name] = {
            "domains": domains,
            "cmd": " ".join(str(part) for part in command),
            "mounts": {str(m.get("Source") or "") for m in item.get("Mounts") or []},
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


def infra_callers(lmap: dict[str, Any]) -> list[tuple[str, str, list[str], dict[str, Any]]]:
    """(container, host, targets, entry) for every infrastructure container with calls."""
    return [
        (container, entry.get("host", "servy.lehel.xyz"), list(targets or []), entry)
        for entry in lmap.get("infrastructure") or []
        for container, targets in (entry.get("calls") or {}).items()
    ]


def dependencies(lmap: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge the map declares, resolved once for both the check and the view.

    Four kinds: `data` (a service to its tier server), `call` (to a service, a
    container, or a tier server), `external` (out of the building) and `socket`
    (to the host's Docker engine). Infrastructure containers declare calls too;
    their edges carry `infra: True` and the container as `src`. A target that
    resolves to nothing is not an edge, it is a typo — `verify_edges` says so.
    """
    tiers = server_tiers(lmap)
    edges: list[dict[str, Any]] = []

    def calls(src: str, host: str, targets: list[str], infra: bool) -> None:
        for target in targets:
            edge = {"src": src, "host": host, "dst": target, "infra": infra}
            if target.startswith("external:"):
                edge.update(kind="external", external=target.split(":", 1)[1])
            elif target == SOCKET:
                edge.update(kind="socket")
            else:
                edge.update(kind="call", tier=tiers.get(target))
            edges.append(edge)

    for svc in lmap.get("services") or []:
        host = svc.get("host", "servy.lehel.xyz")
        data = svc.get("data") or {}
        if data.get("kind") in DATA_KINDS and data.get("server"):
            edges.append(
                {"src": svc["id"], "host": host, "dst": data["server"], "kind": "data",
                 "tier": tiers.get(data["server"]), "infra": False}
            )
        calls(svc["id"], host, svc.get("calls") or [], False)
    for container, host, targets, _ in infra_callers(lmap):
        calls(container, host, targets, True)
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

    callers = [(svc["id"], svc.get("calls") or []) for svc in lmap.get("services") or []]
    callers += [(container, targets) for container, _, targets, _ in infra_callers(lmap)]
    for src, targets in callers:
        for target in targets:
            if target.startswith("external:"):
                if target.split(":", 1)[1] not in externals:
                    problems.append(f"{src}: calls {target}, which is not in externals[]")
            elif (
                target != SOCKET
                and target not in services
                and target not in containers_of
                and target not in infra
                and target not in tiers
            ):
                problems.append(
                    f"{src}: calls {target}, which is not a service, a container, "
                    "a tier server or docker:socket"
                )
    for entry in lmap.get("infrastructure") or []:
        for container in entry.get("calls") or {}:
            if container not in (entry.get("containers") or []):
                problems.append(
                    f"infrastructure {entry.get('project')}: calls are declared for "
                    f"{container}, which is not one of its containers"
                )
    problems += verify_socket_claims(lmap, repo)

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


def verify_socket_claims(lmap: dict[str, Any], repo: Path) -> list[str]:
    """`docker:socket` against the compose files, in both directions.

    Whoever mounts the socket can command every container on the host, so a mount
    nobody declared is the edge most worth catching. Stacks whose compose lives in
    another repository are left to `--verify-host`.
    """
    derived = derive(repo, list(lmap.get("ignore_projects") or []))
    claims: dict[str, bool] = {}
    for svc in lmap.get("services") or []:
        if svc.get("external_compose"):
            continue
        claim = SOCKET in (svc.get("calls") or [])
        for name in (svc.get("containers") or []) + [svc.get("compose_container")]:
            if name:  # a name on two hosts (traefik.traefik) must be claimed by both
                claims[name] = claims.get(name, True) and claim
    for entry in lmap.get("infrastructure") or []:
        if entry.get("external_compose"):
            continue
        for container in entry.get("containers") or []:
            claim = SOCKET in ((entry.get("calls") or {}).get(container) or [])
            claims[container] = claims.get(container, True) and claim
    problems: list[str] = []
    for container, entry in sorted(derived.items()):
        if entry.get("ignored") or container not in claims:
            continue
        if entry["socket"] and not claims[container]:
            problems.append(
                f"{container}: its compose file mounts the Docker socket, but the map "
                "does not claim docker:socket"
            )
        if claims[container] and not entry["socket"]:
            problems.append(
                f"{container}: the map claims docker:socket, but its compose file "
                "mounts no socket"
            )
    return problems


URL_HOST = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/\s]*@)?([A-Za-z0-9_.-]+)")
BARE_HOST = re.compile(r"^([A-Za-z0-9_.-]+)(?::\d+)?$")


def verify_live_unclaimed(
    lmap: dict[str, Any], live: dict[str, dict[str, Any]], host: str
) -> list[str]:
    """The other direction: an env that names another container needs an edge.

    Every value that is a URL (`http://finance.firefly:8080`, `redis://…`) or a bare
    `host[:port]` is resolved against the containers running on `host` — by full
    name, or by compose service name inside the caller's own project, the two names
    docker DNS answers to. A hit no `calls:` or `data:` edge covers is drift: that
    is how Queen → Firefly went unseen. Only the variable's NAME is reported, never
    its value, because these envs carry credentials.
    """
    services = {s["id"]: s for s in lmap.get("services") or []}
    owners: dict[str, tuple[str, set[str]]] = {}  # container -> (map id, its own containers)

    def claimed(targets: list[str], data_server: str | None) -> set[str]:
        out: set[str] = {data_server} if data_server else set()
        for target in targets:
            out |= set(services[target].get("containers") or []) if target in services else {target}
        return out

    edges: dict[str, set[str]] = {}
    for svc in services.values():
        if svc.get("host", "servy.lehel.xyz") != host:
            continue
        own = set(svc.get("containers") or [])
        edges[svc["id"]] = claimed(svc.get("calls") or [], (svc.get("data") or {}).get("server"))
        for container in own:
            owners[container] = (svc["id"], own)
    for entry in lmap.get("infrastructure") or []:
        if entry.get("host", "servy.lehel.xyz") != host:
            continue
        for container in entry.get("containers") or []:
            owners[container] = (container, {container})
            edges[container] = claimed((entry.get("calls") or {}).get(container) or [], None)

    problems: list[str] = []
    for container, (src, own) in sorted(owners.items()):
        entry = live.get(container)
        if entry is None:
            continue
        project = container.split(".", 1)[0]
        for line in entry["env"].splitlines():
            key, _, value = line.partition("=")
            names = URL_HOST.findall(value)
            bare = BARE_HOST.match(value.strip())
            if bare:
                names.append(bare.group(1))
            for name in names:
                target = name if name in live else "%s.%s" % (project, name)
                if target not in live or target in own or target in edges[src]:
                    continue
                problems.append(
                    f"{src}: {container} env {key} names {target} on {host}, "
                    "but the map has no calls or data edge to it"
                )
    return sorted(set(problems))


def verify_live_calls(
    lmap: dict[str, Any], live: dict[str, dict[str, Any]], host: str
) -> list[str]:
    """Every non-external call against the containers that have to carry it.

    A call to a container or service is real when caller and target share a docker
    network other than `proxy` (or `proxy` itself, when Traefik is one end), or
    the caller's env or command names the target. A call to a tier
    server is real when the server is named or the caller sits on the tier's
    network. `docker:socket` is real when the socket (or /var/run) is mounted.
    """
    services = {s["id"]: s for s in lmap.get("services") or []}
    tiers = server_tiers(lmap)
    problems: list[str] = []

    def entries_of(names: list[str]) -> list[dict[str, Any]]:
        return [live[n] for n in names if n in live]

    callers: list[tuple[str, list[str], list[str]]] = []
    for svc in services.values():
        if svc.get("host", "servy.lehel.xyz") == host:
            callers.append((svc["id"], svc.get("containers") or [], svc.get("calls") or []))
    for container, chost, targets, _ in infra_callers(lmap):
        if chost == host:
            callers.append((container, [container], targets))

    for src, names, targets in callers:
        mine = entries_of(names)
        if not mine:
            continue  # not running: verify_live reports a missing service
        said = "\n".join(e["env"] + "\n" + e["cmd"] for e in mine)
        networks = set().union(*(e["networks"] for e in mine))
        mounts = set().union(*(e["mounts"] for e in mine))
        for target in targets:
            if target.startswith("external:"):
                continue  # verify_live_edges
            if target == SOCKET:
                if not any(mounts_socket(m) for m in mounts):
                    problems.append(f"{src}: map says it uses the Docker socket, {host} mounts none")
                continue
            if target in tiers:
                token = target.split(".")[0].replace("-", "_")
                if target not in said and not any(token in n for n in networks):
                    problems.append(
                        f"{src}: map says it reaches {target}, but nothing on {host} names it "
                        f"and it sits on no {token} network"
                    )
                continue
            if target in services:
                theirs_names = services[target].get("containers") or []
            else:
                theirs_names = [target]
            theirs = entries_of(theirs_names)
            if not theirs:
                problems.append(f"{src}: calls {target}, which is not running on {host}")
                continue
            shared = networks & set().union(*(e["networks"] for e in theirs))
            if "traefik.traefik" not in theirs_names and "traefik.traefik" not in names:
                # Nearly everything is on `proxy`; sharing it proves only that Traefik
                # can reach both. It counts as evidence only when Traefik is one end.
                shared.discard("proxy")
            short = {n.split(".", 1)[-1] for n in theirs_names} | set(theirs_names)
            if not shared and not any(word in said for word in short):
                problems.append(
                    f"{src}: map says it calls {target}, but on {host} they share no "
                    "network and nothing names it"
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
  .chip .tk{opacity:.9;letter-spacing:.06em}
  .tk-high{color:var(--high)} .tk-nonprod{color:var(--nonprod)}
  .tk-business{color:var(--business)} .tk-private{color:var(--private)}
  .chips.tiers{display:grid;grid-template-columns:1fr 1fr;gap:6px}
  .tier-block{border:1px solid var(--rule);background:var(--paper);padding:5px 8px 6px;min-width:0}
  .tier-h{display:flex;align-items:baseline;gap:6px;min-width:0}
  .tier-h b{font-family:"IBM Plex Mono",monospace;font-size:9.5px;font-weight:500;
    letter-spacing:.06em;text-transform:uppercase;color:var(--ink)}
  .tier-s{display:block;font-family:"IBM Plex Mono",monospace;font-size:9px;
    color:var(--muted);margin-top:2px;line-height:1.35;overflow-wrap:anywhere}
  .tier-r{font-size:10.5px;line-height:1.35;color:#3c3d31;margin-top:3px}
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
  .fn{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;margin-bottom:8px}
  .fn-zone-card{min-width:0;background:var(--card);border:1px solid var(--ink);padding:16px 18px 10px}
  .fn-zone-h{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    border-bottom:1px solid var(--rule);padding-bottom:8px;margin-bottom:8px}
  .fn-zone-h h3{margin:0;font-family:"Instrument Serif",serif;font-weight:400;font-size:26px}
  .fn-zone-h span{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
    letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
  .fn-scroll{overflow-x:auto}
  .fn-svg{display:block;width:100%;min-width:860px;max-width:1384px;height:auto}
  .fn-head{font:400 10px "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.14em;
    text-transform:uppercase;fill:var(--muted)}
  .fn-node rect{fill:var(--paper);stroke:var(--rule)}
  .fn-label{font:500 12px "Bricolage Grotesque",system-ui,sans-serif;fill:var(--ink)}
  .fn-sub{font:400 9.5px "IBM Plex Mono",ui-monospace,monospace;fill:var(--muted)}
  .t-zone rect{fill:var(--ink);stroke:var(--ink)}
  .t-zone .fn-label{font:400 19px "Instrument Serif",serif;fill:var(--paper)}
  .t-host .fn-label{font:400 11.5px "IBM Plex Mono",ui-monospace,monospace}
  .t-host rect{fill:transparent;stroke:none}
  .t-svc rect{fill:var(--card);stroke:var(--ink)}
  .t-svc.h-servy rect{stroke:var(--servy)} .t-svc.h-codey rect{stroke:var(--codey)}
  .t-svc.h-test rect{stroke:var(--test)}
  .t-svc,.t-host{cursor:default}
  .t-high rect{stroke:var(--high);stroke-width:1.5} .t-nonprod rect{stroke:var(--nonprod);stroke-width:1.5}
  .t-business rect{stroke:var(--business);stroke-width:1.5} .t-private rect{stroke:var(--private);stroke-width:1.5}
  .t-ext rect,.t-app rect,.t-infra rect{stroke:var(--ext);stroke-dasharray:3 2}
  .fn-link{fill:none;stroke:var(--rule);stroke-width:1.2}
  .fn-link.t-high{stroke:var(--high)} .fn-link.t-nonprod{stroke:var(--nonprod)}
  .fn-link.t-business{stroke:var(--business)} .fn-link.t-private{stroke:var(--private)}
  .fn-link.t-ext,.fn-link.t-app,.fn-link.t-infra{stroke:var(--ext);stroke-dasharray:4 3}
  .fn-svg .fn-node,.fn-svg .fn-link{transition:opacity .15s}
  .fn-focus .fn-node,.fn-focus .fn-link{opacity:.18}
  .fn-focus .fn-on{opacity:1}
  .fn-focus .fn-link.fn-on{stroke-width:2.2}
  .fn-host{border-top-width:6px}
  .fn-host.servy{border-top-color:var(--servy)} .fn-host.codey{border-top-color:var(--codey)}
  .fn-role{font-family:"IBM Plex Mono",ui-monospace,monospace}
  .fn-tag{margin:0 0 6px;font-size:12.5px;color:var(--muted)}
  .fn-link.loop{stroke:var(--ext);stroke-dasharray:4 3}
  .t-role .fn-label{font:italic 400 12px "Bricolage Grotesque",system-ui,sans-serif;fill:var(--muted)}
  .t-inrow rect{fill:transparent;stroke-dasharray:3 2}
  .t-inrow .fn-label{font:400 11.5px "IBM Plex Mono",ui-monospace,monospace}
  .t-socket rect{fill:var(--ink);stroke:var(--ink)}
  .t-socket .fn-label{fill:var(--paper)} .t-socket .fn-sub{fill:#c9c4b4}
  .fn-link.t-socket{stroke:var(--ink);stroke-dasharray:2 3;stroke-width:1}
  .fn-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;padding-top:10px;
    border-top:1px solid var(--rule);font-family:"IBM Plex Mono",ui-monospace,monospace;
    font-size:10px;letter-spacing:.06em;color:var(--muted)}
  .fn-legend span{display:inline-flex;align-items:center;gap:6px}
  .lg-box{display:inline-block;width:16px;height:10px;border:1px solid var(--ink);background:var(--card)}
  .lg-box.h-servy{border-color:var(--servy)} .lg-box.h-codey{border-color:var(--codey)}
  .lg-box.lg-inrow{border-style:dashed;background:transparent}
  .lg-line{display:inline-block;width:20px;height:0;border-top:2px solid var(--rule)}
  .lg-line.t-high{border-color:var(--high)} .lg-line.t-nonprod{border-color:var(--nonprod)}
  .lg-line.t-business{border-color:var(--business)} .lg-line.t-private{border-color:var(--private)}
  .lg-line.lg-dash{border-top:2px dashed var(--ext)}
  .notes{margin-top:18px}
  .nt-k{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--muted)}
  .notes{grid-template-columns:repeat(3,1fr)}
  .notes .dot{width:8px;height:8px;display:inline-block;vertical-align:middle;transform:none}
  @media(max-width:1080px){ .hosts{grid-template-columns:1fr 1fr} .connectors{display:none}
    .lane-flow.inward{grid-template-columns:auto auto 1fr 1fr} }
  @media(max-width:820px){
    .mast-body{grid-template-columns:1fr}
    .edge{grid-template-columns:1fr}
    .arrow{display:none}
    .hosts{grid-template-columns:1fr}
    .foundation,.notes{grid-template-columns:1fr}
    .lane{grid-template-columns:1fr}
    .lane-k{border-right:0;border-bottom:1px solid var(--rule);
      justify-content:flex-start;text-align:left}
    .lane-flow.inward{grid-template-columns:1fr}
    .chips.tiers{grid-template-columns:1fr}
  }
"""

TIER_DOT = {"high": "d-high", "nonprod": "d-nonprod", "business": "d-business", "private": "d-private"}
HOST_CLASS = {"servy.lehel.xyz": "servy", "codey.lehel.xyz": "codey", "servyy-test.lxd": "test"}


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- #
# domain → service → data flows
# --------------------------------------------------------------------------- #
LOCAL_DATA = {"sqlite", "volume", "tsdb"}


def show_domain(domain: str) -> str:
    """IDN hostnames in their readable form (xn--hfer… → höfer…)."""
    try:
        return domain.encode("ascii").decode("idna")
    except UnicodeError:
        return domain


def service_flows(lmap: dict[str, Any], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One graph per server: domains → service → data → beyond, one row per caller.

    Service first: every service is a row, led by all the hostnames it answers on,
    and so is every infrastructure container that calls something (its role stands
    where the domains would be). Tier servers, externals, shared containers and each
    host's Docker engine are shared nodes, so different callers meet at one box;
    a call to another row is a loop between the two. Rows are ordered by the tier
    server they reach, then by project, so callers of one server sit together.
    Every node and link comes from fields `--verify` checks: `domains`, `data:`,
    and `dependencies()`.
    """
    services = {s["id"]: s for s in lmap.get("services") or []}
    externals = {x["id"]: x for x in lmap.get("externals") or []}
    tiers = server_tiers(lmap)
    tier_defs = lmap.get("tiers") or {}
    tier_rank = {name: n for n, name in enumerate(tier_defs)}
    roles = {
        (c, entry.get("host", "servy.lehel.xyz")): entry.get("role", "")
        for entry in lmap.get("infrastructure") or []
        for c in entry.get("containers") or []
    }

    rows: dict[str, dict[str, Any]] = {}
    for svc in services.values():
        rows[svc["id"]] = {"id": svc["id"], "src": svc["id"], "infra": False,
                           "host": svc.get("host", "servy.lehel.xyz"),
                           "project": svc.get("project", ""), "svc": svc}
    for container, host, _, entry in infra_callers(lmap):
        rid = "%s@%s" % (container, host)
        rows[rid] = {"id": rid, "src": container, "infra": True, "host": host,
                     "project": entry.get("project", ""), "role": entry.get("role", "")}
    row_of: dict[tuple[str, str], str] = {}
    for rid, row in rows.items():
        if row["infra"]:
            row_of[(row["src"], row["host"])] = rid
        else:
            for c in row["svc"].get("containers") or []:
                row_of[(c, row["host"])] = rid
    mine = {rid: [x for x in edges if x["src"] == row["src"] and x["host"] == row["host"]
                  and x["infra"] == row["infra"]] for rid, row in rows.items()}

    def short(host: str) -> str:
        return host.split(".")[0]

    def target(edge: dict[str, Any]) -> dict[str, Any] | str:
        """A node for the edge's far end, or the id of the row it loops to."""
        dst, host = edge["dst"], edge["host"]
        if dst in tiers:
            tier = tier_defs.get(tiers[dst]) or {}
            rpo = (tier.get("backup") or {}).get("rpo")
            return {"id": dst, "label": dst, "cls": "t-%s" % tiers[dst], "col": 2,
                    "sub": "tier %s%s" % (tiers[dst], " · RPO %s" % rpo if rpo else ""),
                    "title": "%s — tenants: %s" % (dst, ", ".join(tier.get("tenants") or []))}
        if edge["kind"] == "external":
            ext = externals.get(edge["external"]) or {}
            src = services.get(edge["src"]) if not edge["infra"] else None
            col = 2 if src and (src.get("data") or {}).get("kind") == "external" \
                and ext.get("kind") == "saas" else 3
            return {"id": dst, "label": ext.get("title", edge["external"]), "col": col,
                    "sub": ext.get("path") or ext.get("via") or ext.get("host") or "external",
                    "cls": "t-ext"}
        if edge["kind"] == "socket":
            return {"id": "docker@" + host, "label": "Docker engine (%s)" % short(host),
                    "sub": "/var/run/docker.sock", "cls": "t-socket", "col": 3}
        if dst in services:
            return dst
        if (dst, host) in row_of:
            return row_of[(dst, host)]
        role = roles.get((dst, host), "shared container")
        return {"id": "%s@%s" % (dst, host), "label": dst, "cls": "t-infra", "col": 3,
                "sub": role.split(" — ")[0],
                "title": "%s — %s" % (dst, role)}

    def rank(rid: str) -> tuple:
        row = rows[rid]
        server = next((x["dst"] for x in mine[rid] if x["dst"] in tiers), "")
        if server:
            return (0, tier_rank.get(tiers[server], 99), server, row["infra"], row["project"], rid)
        data = (row.get("svc") or {}).get("data") or {}
        if data.get("kind") == "external":
            return (1, 0, "", row["infra"], row["project"], rid)
        bucket = 2 if mine[rid] else 3 if data.get("kind") in LOCAL_DATA else 4
        return (bucket, 0, "", row["project"], row["host"], row["infra"], rid)

    order = sorted(rows, key=rank)
    servers = [h["name"] for h in lmap.get("hosts") or []]
    servers += sorted({r["host"] for r in rows.values()} - set(servers))
    flows = []
    # One graph per server, and only servers with something on them: the test host
    # runs the same compose files and has no row of its own, so it has no graph.
    for server in servers:
        if not any(r["host"] == server for r in rows.values()):
            continue
        links: list[tuple[str, str, str]] = []
        cols: list[dict[str, dict[str, Any]]] = [{}, {}, {}, {}]
        for rid in [r for r in order if rows[r]["host"] == server]:
            row = rows[rid]
            host = row["host"]
            hid = "%s@domains" % rid
            if row["infra"]:
                cols[0][hid] = {"id": hid, "lines": [row["role"] or "infrastructure"], "sub": "",
                                "cls": "t-host t-role", "svc": rid, "title": "no public name"}
                cols[1][rid] = {"id": rid, "label": row["src"], "sub": "infrastructure",
                                "cls": "t-svc t-inrow h-%s" % HOST_CLASS.get(host, "servy"), "svc": rid}
            else:
                svc = row["svc"]
                data = svc.get("data") or {}
                local = data.get("kind") if data.get("kind") in LOCAL_DATA else ""
                domains = sorted(svc.get("domains") or [], key=lambda d: (d.count("."), len(d), d))
                cols[0][hid] = {"id": hid, "lines": [show_domain(d) for d in domains] or ["no public name"],
                                "sub": "", "cls": "t-host", "svc": rid, "title": "\n".join(domains)}
                cols[1][rid] = {"id": rid, "label": svc.get("name", rid),
                                "sub": local,
                                "cls": "t-svc h-%s" % HOST_CLASS.get(host, "servy"), "svc": rid}
            links.append((hid, rid, "t-host"))
            for edge in mine[rid]:
                node = target(edge)
                if isinstance(node, str) and rows[node]["host"] == server:
                    links.append((rid, node, "t-app loop"))
                    continue
                if isinstance(node, str):  # a row on another server: draw it as a node
                    other = rows[node]
                    node = {"id": node, "col": 3, "cls": "t-app",
                            "label": (other.get("svc") or {}).get("name", other["src"]),
                            "sub": "on %s" % short(other["host"])}
                cols[node["col"]].setdefault(node["id"], node)
                links.append((rid, node["id"], node["cls"]))
        mine_svcs = [r["svc"] for r in rows.values() if r["host"] == server and not r["infra"]]
        flows.append({
            "host": server, "title": server, "cols": cols, "links": links,
            "services": len(mine_svcs),
            "infra": sum(1 for r in rows.values() if r["infra"] and r["host"] == server),
            "hosts": sum(len(svc.get("domains") or []) for svc in mine_svcs),
        })
    return flows


def render_flow_svg(flow: dict[str, Any]) -> str:
    cols = flow["cols"]
    col_x = [0, 400, 720, 1040]
    col_w = [340, 250, 250, 300]
    heads = ("domains", "service", "data", "beyond")
    node_h, gap, top, line = 40, 12, 30, 15
    svc_order = list(cols[1])

    # Rows follow the services; a row is as tall as its domain list.
    tops: dict[str, float] = {}
    heights: dict[str, float] = {}
    y = top
    for sid in svc_order:
        hid = "%s@domains" % sid
        row = max(node_h, line * len(cols[0][hid]["lines"]) + 12)
        tops[hid], heights[hid] = y, row
        tops[sid], heights[sid] = y + (row - node_h) / 2, node_h
        y += row + gap
    bottom = y - gap
    for c in (2, 3):
        # Level with the services that reach them, pushed apart, kept in frame.
        def want(nid: str) -> float:
            ys = [tops[a] for a, b, _ in flow["links"] if b == nid and a in cols[1]]
            return sum(ys) / len(ys) if ys else top
        ids = sorted(cols[c], key=want)
        placed: list[float] = []
        for nid in ids:
            placed.append(max(want(nid), placed[-1] + node_h + gap) if placed else max(want(nid), top))
        overflow = placed[-1] + node_h - bottom if placed else 0
        if overflow > 0:
            placed = [p - overflow for p in placed]
            for n in range(len(placed) - 2, -1, -1):
                placed[n] = min(placed[n], placed[n + 1] - node_h - gap)
        for nid, p in zip(ids, placed):
            tops[nid], heights[nid] = p, node_h
        bottom = max(bottom, (placed[-1] + node_h) if placed else bottom)
    height = int(bottom + 4)

    parts = ['<text class="fn-head" x="%d" y="12">%s</text>' % (col_x[c], e(h)) for c, h in enumerate(heads)]
    nodes_svg: list[str] = []
    pos: dict[str, tuple[int, float]] = {}
    for c, nodes in enumerate(cols):
        for nid, node in nodes.items():
            y, h = tops[nid], heights[nid]
            mid = y + h / 2
            pos[nid] = (c, mid)
            x = col_x[c] + 10
            if node.get("lines"):
                lines = node["lines"]
                first = mid + 4 - line * (len(lines) - 1) / 2
                label = "".join(
                    '<text class="fn-label" x="%d" y="%.1f">%s</text>' % (x, first + line * n, e(t))
                    for n, t in enumerate(lines)
                )
            elif node["sub"]:
                label = (
                    '<text class="fn-label" x="%d" y="%.1f">%s</text>'
                    '<text class="fn-sub" x="%d" y="%.1f">%s</text>'
                    % (x, mid - 2, e(node["label"]), x, mid + 12, e(node["sub"]))
                )
            else:
                label = '<text class="fn-label" x="%d" y="%.1f">%s</text>' % (x, mid + 5, e(node["label"]))
            reach = [node["svc"]] if node.get("svc") else sorted(
                {a for a, b, _ in flow["links"] if b == nid and a in cols[1]})
            nodes_svg.append(
                '<g class="fn-node %s" data-of="%s"><title>%s</title>'
                '<rect x="%d" y="%.1f" width="%d" height="%.1f" rx="3"/>%s</g>'
                % (node["cls"], e(" ".join(reach)), e(node.get("title") or node["label"]),
                   col_x[c], y, col_w[c], h, label)
            )
    for a, b, cls in flow["links"]:
        (ca, ya), (cb, yb) = pos[a], pos[b]
        if "loop" in cls:
            x1 = col_x[ca] + col_w[ca]
            bend = x1 + 22 + min(80, abs(yb - ya) / 10)
            parts.append(
                '<path class="fn-link %s" data-s="%s" d="M%d %.1f C%d %.1f %d %.1f %d %.1f"/>'
                % (cls, e(a), x1, ya, bend, ya, bend, yb, x1 + 4, yb)
            )
            continue
        x1, x2 = col_x[ca] + col_w[ca], col_x[cb]
        mid = (x1 + x2) / 2
        owner = a if a in cols[1] else b
        parts.append(
            '<path class="fn-link %s" data-s="%s" d="M%d %.1f C%.1f %.1f %.1f %.1f %d %.1f"/>'
            % (cls, e(owner), x1, ya, mid, ya, mid, yb, x2, yb)
        )
    return (
        '<svg class="fn-svg" viewBox="-2 0 1344 %d" role="img" aria-label="%s: domains, '
        'services, data and dependencies">%s%s</svg>'
        % (height, e(flow["title"]), "".join(parts), "".join(nodes_svg))
    )


def render_domain_flows(lmap: dict[str, Any], edges: list[dict[str, Any]]) -> str:
    hosts = {h["name"]: h for h in lmap.get("hosts") or []}
    blocks = []
    for f in service_flows(lmap, edges):
        host = hosts.get(f["host"]) or {}
        specs = host.get("specs") or {}
        facts = " · ".join(str(x) for x in (
            specs.get("cpu"), specs.get("mem"), specs.get("disk"), specs.get("os"),
            "%s containers" % host["containers"] if host.get("containers") else None,
        ) if x)
        blocks.append(
            '  <div class="fn-zone-card fn-host %s"><div class="fn-zone-h"><h3>%s</h3>'
            '<span class="fn-role">%s</span><span>%s</span></div>'
            '<p class="fn-tag">%s — %d services · %d infrastructure · %d hostnames. Hover a row to trace it.</p>'
            '<div class="fn-scroll">%s</div>%s</div>\n'
            % (HOST_CLASS.get(f["host"], "servy"), e(f["host"]), e(host.get("role", "")), e(facts),
               e(host.get("tagline", "")), f["services"], f["infra"], f["hosts"],
               render_flow_svg(f), FLOW_LEGEND)
        )
    return '  <div class="fn">\n%s  </div>\n%s' % ("".join(blocks), FLOW_JS)


FLOW_LEGEND = (
    '<div class="fn-legend">'
    '<span><i class="lg-box lg-inrow"></i>infrastructure, no public name</span>'
    '<span><i class="lg-line t-high"></i>high</span><span><i class="lg-line t-nonprod"></i>nonprod</span>'
    '<span><i class="lg-line t-business"></i>business</span><span><i class="lg-line t-private"></i>private</span>'
    '<span><i class="lg-line lg-dash"></i>call · external · socket</span>'
    '</div>'
)


def render_notes(lmap: dict[str, Any], edges: list[dict[str, Any]]) -> str:
    """What the graph cannot carry: each tier's tenants and backup, the one door
    out, and the control plane (which crosses hosts, so it is no row's call)."""
    tiers = lmap.get("tiers") or {}
    services = {s["id"]: s for s in lmap.get("services") or []}
    externals = {x["id"]: x for x in lmap.get("externals") or []}
    cards: list[tuple[str, str, str]] = []
    for name, tier in tiers.items():
        backup = tier.get("backup") or {}
        bits = [
            "Servers: %s." % " · ".join(sv["name"] for sv in tier.get("servers") or []),
            "Tenants: %s." % (", ".join(tier.get("tenants") or []) or "none"),
            "Backup: %s%s." % (backup.get("kind", "—"),
                               ", RPO %s" % backup["rpo"] if backup.get("rpo") else ""),
        ]
        if tier.get("notes"):
            bits.append(str(tier["notes"]))
        cards.append(("tier", name, " ".join(bits)))

    def disp(name: str) -> str:
        if name in services:
            return services[name].get("name", name)
        for svc in services.values():
            if name in (svc.get("containers") or []):
                return svc.get("name", name)
        return name

    door = externals.get("opencode") or {}
    users = sorted(disp(x["src"]) for x in edges
                   if x["kind"] == "external" and x.get("external") == "opencode")
    text = (
        "%s reach %s through %s. The API key stops at the gate, which holds the Basic "
        "credential, so no app ever carries the server password; the API-key router is "
        "the only door." % (", ".join(users) or "No app", door.get("title", "OpenCode"),
                            door.get("path") or door.get("via", "code.lehel.xyz"))
    )
    atlas = externals.get("atlas")
    if atlas:
        saas = sorted(disp(x["src"]) for x in edges
                      if x["kind"] == "external" and x.get("external") == "atlas")
        text += " %s keep their data in %s — outside every tier, so no restic repo of ours covers it." % (
            " and ".join(saas) or "No app", atlas.get("title", "Atlas"))
    cards.append(("outward", "One door out", text))

    control = " ".join(
        "%s → %s: %s." % (disp(str(r.get("from"))),
                          "every container" if r.get("to") == "*" else disp(str(r.get("to"))),
                          r.get("label", ""))
        for r in lmap.get("control") or []
    )
    cards.append(("control", "Control plane", control + " Portainer on servy drives the agent on codey, "
                  "so control crosses the machine boundary the app path does."))
    body = "".join(
        '    <div class="f-card nt-%s"><span class="nt-k">%s</span><h3>%s%s</h3><p>%s</p></div>\n'
        % (e(k), e(k), '<span class="dot d-%s"></span> ' % e(title) if k == "tier" else "",
           e(title), e(text)) for k, title, text in cards
    )
    return '  <div class="foundation notes">\n%s  </div>\n' % body


FLOW_JS = """  <script>
  document.querySelectorAll('.fn-svg').forEach(function (svg) {
    function mark(sid, on) {
      svg.classList.toggle('fn-focus', on);
      svg.querySelectorAll('[data-s="' + sid + '"], [data-of~="' + sid + '"]').forEach(function (el) {
        el.classList.toggle('fn-on', on);
      });
    }
    svg.querySelectorAll('.t-svc, .t-host').forEach(function (node) {
      var sid = node.getAttribute('data-of');
      node.addEventListener('mouseenter', function () { mark(sid, true); });
      node.addEventListener('mouseleave', function () { mark(sid, false); });
    });
  });
  </script>
"""


def render_html(lmap: dict[str, Any]) -> str:
    tiers = lmap.get("tiers") or {}
    hosts = lmap.get("hosts") or [{"name": "servy.lehel.xyz", "role": "production"}]
    # The poster shows the servers something runs on; the test host mirrors them
    # and has no row of its own, so it is not counted here either.
    placed = {s.get("host", "servy.lehel.xyz") for s in lmap.get("services") or []}
    placed |= {i.get("host", "servy.lehel.xyz") for i in lmap.get("infrastructure") or []}
    hosts = [h for h in hosts if h["name"] in placed] or hosts
    services = lmap.get("services") or []
    domains = sorted({d for s in services for d in (s.get("domains") or [])})
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
        ("containers", str(total_containers), "across %d servers" % len(hosts)),
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
        '  <div class="sec-head"><span class="sec-num">2</span><h2>Servers, domain to data</h2>'
        '<span class="sub">production servers only — every service with the names it answers on, '
        'what it reads and what it calls</span><span class="rule"></span></div>\n'
    )
    out.append(render_domain_flows(lmap, edges))
    out.append(render_notes(lmap, edges))

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
        problems += verify_edges(lmap, repo)
        for host in args.verify_host:
            live = derive_live(host)
            problems += verify_live(lmap, live, host)
            problems += verify_live_edges(lmap, live, host)
            problems += verify_live_calls(lmap, live, host)
            problems += verify_live_unclaimed(lmap, live, host)
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
