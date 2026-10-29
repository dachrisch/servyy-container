#!/usr/bin/env python3
"""Fail a deploy when a compose file publishes a container port on every
interface.

Why this exists: Docker writes its own FORWARD/nat rules and bypasses ufw, so a
`ports: - "8080:8080"` in any compose file is reachable from the internet the
moment the container starts. Both repos are public and the compose files are
readable now, so a copy-pasted `ports:` line is a realistic accident. The only
service that may bind 0.0.0.0 is the reverse proxy itself (80/443); everything
else must publish to 127.0.0.1 (tunnels, sidecars) or not publish at all.

Runs on the target host, where the compose files are plaintext (they are
git-crypt ciphertext in the repo, so CI cannot check them).

Usage: check_published_ports.py <compose-root> [<compose-root> ...]
Exit 0 = clean, 1 = at least one offending publish, 2 = a file could not be parsed.
"""
import glob
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - the deploy hosts have PyYAML
    print('check_published_ports: PyYAML missing on the target', file=sys.stderr)
    sys.exit(2)

# service -> host ports it is allowed to publish on all interfaces
ALLOWED = {
    ('traefik/docker-compose.yml', 'reverse-proxy'): {'80', '443'},
}


def published_on_all_interfaces(port):
    """Return the host-side port when this entry binds every interface."""
    if isinstance(port, dict):  # long syntax
        if 'published' in port or 'host_ip' in port:
            host_ip = str(port.get('host_ip') or '')
            published = str(port.get('published') or '')
            if host_ip in ('127.0.0.1', '::1'):
                return None
            return published or 'random'
        return None
    text = str(port)
    if '/' in text:
        text = text.split('/', 1)[0]
    parts = text.split(':')
    if len(parts) == 1:            # container port only -> random host port, all interfaces
        return 'random'
    if len(parts) == 2:            # host:container
        return parts[0]
    # ip:host:container (ip may be bracketed IPv6)
    host_ip = ':'.join(parts[:-2])
    if host_ip.strip('[]') in ('127.0.0.1', '::1'):
        return None
    return parts[-2]


def main(roots):
    problems = []
    parse_errors = []
    checked = 0
    for root in roots:
        for pattern in ('*/docker-compose*.yml', '*/docker-compose*.yaml'):
            for path in sorted(glob.glob(f'{root}/{pattern}')):
                rel = path[len(root.rstrip('/')) + 1:]
                try:
                    data = yaml.safe_load(open(path, encoding='utf-8')) or {}
                except Exception as exc:                      # noqa: BLE001
                    parse_errors.append((rel, str(exc)))
                    continue
                checked += 1
                for name, svc in (data.get('services') or {}).items():
                    for port in (svc.get('ports') or []):
                        host_port = published_on_all_interfaces(port)
                        if host_port is None:
                            continue
                        allowed = ALLOWED.get((rel, name), set())
                        if host_port in allowed:
                            continue
                        problems.append((rel, name, str(port), host_port))
    for rel, name, spec, host_port in problems:
        print(f'  PUBLIC PORT: {rel} service {name} publishes {spec!r} '
              f'(host port {host_port} on all interfaces)', file=sys.stderr)
    for rel, exc in parse_errors:
        print(f'  PARSE ERROR: {rel}: {exc}', file=sys.stderr)
    if not problems and not parse_errors:
        print(f'  published-port check: {checked} compose files, no 0.0.0.0 publishes '
              f'outside the reverse proxy')
        return 0
    return 2 if parse_errors else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:] or ['.']))
