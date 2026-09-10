#!/usr/bin/env bash
# Read-only health check for one servyy-container host.
# Usage: check-status.sh <servy.lehel.xyz|codey.lehel.xyz>
set -uo pipefail

HOST="${1:?usage: check-status.sh <servy.lehel.xyz|codey.lehel.xyz>}"

echo "### $HOST ###"

ssh -o ConnectTimeout=8 "$HOST" '
  echo "--- uptime/load ---"; uptime
  echo "--- disk ---"; df -h / 2>/dev/null
  echo "--- memory ---"; free -h
  echo "--- containers NOT Up (crash-loops, exited, unhealthy) ---"
  docker ps -a --format "{{.Names}}\t{{.Status}}" | grep -viE "\sUp " || echo "none - all containers Up"
  echo "--- containers running ---"
  docker ps --format "{{.Names}}\t{{.Status}}"
  echo "--- fail2ban ---"; sudo fail2ban-client status 2>&1
  echo "--- monit ---"; sudo monit summary 2>&1
  echo "--- timers (apt/cleanup/restic) ---"
  systemctl list-timers --all 2>&1 | grep -E "apt-daily-upgrade|docker-cleanup|kernel-cleanup|restic-forget|restic-check|UNIT"
'

# Traefik routing check runs from the caller, not the host itself, so it
# exercises the real public DNS + TLS path instead of internal routing.
case "$HOST" in
  servy.lehel.xyz|lehel.xyz)
    URLS="https://traefik.lehel.xyz https://monitor.lehel.xyz"
    ;;
  codey.lehel.xyz|code.lehel.xyz)
    URLS="https://code.lehel.xyz"
    ;;
  *)
    URLS=""
    ;;
esac

echo "--- HTTPS routing (via Traefik, from caller) ---"
for u in $URLS; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$u" 2>/dev/null || echo "000")
  echo "$u -> $code"
done
