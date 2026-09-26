#!/usr/bin/env bash
# watch-staging.sh — live stage deployment monitor for leaguesphere_stage.*
#
# Single-screen dashboard showing, while watchtower rolls staging updates:
#   - live container status (image digest, Docker health, uptime, gate-wait timer)
#   - latest watchtower-dev log events (stop/create/session, errors highlighted)
#   - real HTTP 200 checks against the public stage endpoint via Traefik
#   - a two-factor health banner (container health AND HTTP 200)
#
# Read-only: only `docker inspect` / `docker logs` over ssh and `curl` from here.
# Usage: ./watch-staging.sh [--once] [STAGE_URL=https://stage.leaguesphere.app]
#   --once   print one snapshot in plain line mode and exit (for pipes/Cron)
# Env: STAGE_URL, SSH_HOST (default servy.lehel.xyz), INTERVAL (default 2),
#      HTTP_INTERVAL (default 10), GATE_TIMEOUT (default 120s, mirrors
#      WATCHTOWER_HEALTH_CHECK_TIMEOUT=2m), LOG_LINES (default 6), HIST (default 20)
set -u

SSH_HOST="${SSH_HOST:-servy.lehel.xyz}"
STAGE_URL="${STAGE_URL:-https://stage.leaguesphere.app}"
INTERVAL="${INTERVAL:-2}"
HTTP_INTERVAL="${HTTP_INTERVAL:-10}"
GATE_TIMEOUT="${GATE_TIMEOUT:-120}"
LOG_LINES="${LOG_LINES:-6}"
HIST_LEN="${HIST:-20}"
CONTAINERS="leaguesphere_stage.www leaguesphere_stage.staging-app"
SHORTNAMES="www staging-app"

for arg in "$@"; do
  case "$arg" in
    --once) ONCE=1 ;;
    STAGE_URL=*) STAGE_URL="${arg#STAGE_URL=}" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
ONCE="${ONCE:-0}"

# --- terminal setup -----------------------------------------------------------
if [ -t 1 ] && [ "$ONCE" -eq 0 ]; then
  UI=1
else
  UI=0
fi
if [ "$UI" -eq 1 ]; then
  RED=$(tput setaf 1); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  trap 'tput cnorm; tput sgr0; exit 0' INT TERM
  tput civis
else
  RED=""; GREEN=""; YELLOW=""; BOLD=""; DIM=""; RESET=""
  trap 'exit 0' INT TERM
fi

# --- state --------------------------------------------------------------------
LOG_CURSOR="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
declare -A DIGEST HEALTH STARTED GATE_T0
HIST=""            # strip of last HTTP results: "." = 200, else status code char
LAST_HTTP="…"
LAST_HTTP_T=""
HTTP_FAIL_STREAK=0
POLL_COUNT=0
STALE=0
LAST_POLL_TS="never"
QUIT=0

ssh_run() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$SSH_HOST" "$@" 2>/dev/null; }

health_color() {
  case "$1" in
    healthy) printf '%s' "$GREEN" ;;
    starting) printf '%s' "$YELLOW" ;;
    unhealthy) printf '%s' "$RED" ;;
    *) printf '%s' "$DIM" ;;
  esac
}

fmt_dur() { # seconds -> 4m12s / 8s
  local s=$1
  if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s/60)) $((s%60)); else printf '%ss' "$s"; fi
}

poll_docker() {
  local out name digest health started_at now
  now="$(date +%s)"
  out="$(ssh_run "for c in $CONTAINERS; do docker inspect --format '{{.Name}}|{{.Image}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-check{{end}}|{{.State.StartedAt}}' \"\$c\" 2>/dev/null; done")"
  [ -z "$out" ] && { STALE=1; return 1; }
  STALE=0
  while IFS='|' read -r name digest health started_at; do
    name="${name#/}"
    digest="$(printf '%s' "$digest" | sed 's/^sha256://' | cut -c1-8)"
    started_epoch="$(date -d "$started_at" +%s 2>/dev/null || echo "$now")"
    if [ "${DIGEST[$name]:-}" != "" ] && [ "${DIGEST[$name]}" != "$digest" ]; then
      DIGEST_PREV[$name]="${DIGEST[$name]}"
      GATE_T0[$name]="$now"
    fi
    if [ "$health" = "starting" ] && [ "${HEALTH[$name]:-}" != "starting" ]; then
      GATE_T0[$name]="$now"
    fi
    DIGEST[$name]="$digest"
    HEALTH[$name]="$health"
    STARTED[$name]="$started_epoch"
  done <<< "$out"
  LAST_POLL_TS="$(date +%H:%M:%S)"
  return 0
}

poll_logs() {
  local raw line ts msg
  raw="$(ssh_run "docker logs --since '$LOG_CURSOR' portainer.watchtower-dev 2>&1 | grep -E 'Stopping|Creating|Session done|Health check|error|rollback|Failed' | tail -n $LOG_LINES")"
  [ -z "$raw" ] && return 0
  LOG_CURSOR="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  while IFS= read -r line; do
    # watchtower logfmt: time="2026-..T12:03:31+02:00" level=.. msg=".."
    ts="$(printf '%s' "$line" | sed -n 's/.*T\([0-9:]*\)+.*/\1/p')"
    msg="$(printf '%s' "$line" | sed -n 's/.*msg="\([^"]*\)".*/\1/p')"
    [ -z "$msg" ] && msg="$line"
    LOG_BUF+=("$ts $msg")
  done <<< "$raw"
  # keep last LOG_LINES (+ some headroom for highlight scan)
  local n=${#LOG_BUF[@]}
  if [ "$n" -gt "$LOG_LINES" ]; then
    LOG_BUF=("${LOG_BUF[@]:$((n-LOG_LINES))}")
  fi
}
LOG_BUF=()

poll_http() {
  local res code time_s
  # -L: stage root 301-redirects to the app entry point; the final code is
  # what counts (200 = serving). Non-200 final (502/404/000) = attention.
  res="$(curl -sL --max-redirs 3 -o /dev/null -m 12 -w '%{http_code} %{time_total}' "$STAGE_URL" 2>/dev/null)" || res="000 0"
  code="${res%% *}"; time_s="${res##* }"
  LAST_HTTP="$code"; LAST_HTTP_T="$time_s"
  if [ "$code" = "200" ]; then
    HIST="${HIST}·"; HTTP_FAIL_STREAK=0
  else
    HIST="${HIST}${code:0:1}"; HTTP_FAIL_STREAK=$((HTTP_FAIL_STREAK+1))
  fi
  [ "${#HIST}" -gt "$HIST_LEN" ] && HIST="${HIST: -$HIST_LEN}"
}

print_row() { # shortname fullname
  local sn=$1 fn=$2 d h up gate col extra=""
  d="${DIGEST[$fn]:-…}"; h="${HEALTH[$fn]:-?}"
  col="$(health_color "$h")"
  if [ -n "${STARTED[$fn]:-}" ]; then up="up $(fmt_dur $(( $(date +%s) - STARTED[$fn] )))"; else up="up ?"; fi
  if [ -n "${DIGEST_PREV[$fn]:-}" ] && [ "${DIGEST_PREV[$fn]}" != "$d" ]; then
    extra=" ${DIM}(was ${DIGEST_PREV[$fn]})${RESET}"
  fi
  gate=""
  if [ "$h" = "starting" ]; then
    t0="${GATE_T0[$fn]:-$(date +%s)}"
    gate="  gate: $(fmt_dur $(( $(date +%s) - t0 ))) / $(fmt_dur "$GATE_TIMEOUT")"
  fi
  printf '│ %-11s %-8s %s%-9s%s  %-9s%s%s\n' "$sn" "$d" "$col" "$h" "$RESET" "$up" "$gate" "$extra"
}

render() {
  local width i line col banner bcol
  width="$(tput cols 2>/dev/null || echo 80)"
  [ "$width" -gt 100 ] && width=100
  [ "$width" -lt 60 ] && width=60
  local bar; bar="$(printf '─%.0s' $(seq 1 $((width-2))))"

  # banner verdict: two-factor — container health AND http
  local bad=0 updating=0 sn fn
  i=0; for fn in $CONTAINERS; do
    case "${HEALTH[$fn]:-?}" in
      unhealthy) bad=1 ;;
      starting) updating=1 ;;
    esac
  done
  if [ "$bad" -eq 1 ] || { [ "$LAST_HTTP" != "200" ] && [ "$LAST_HTTP" != "…" ]; }; then
    banner="● ATTENTION — stage is not fully serving"; bcol="$RED"
  elif [ "$updating" -eq 1 ]; then
    banner="● UPDATING — watchtower rollout in progress"; bcol="$YELLOW"
  else
    banner="● ALL HEALTHY — containers green, HTTP 200"; bcol="$GREEN"
  fi

  clear
  printf '┌%s┐\n' "$bar"
  printf '│ %sSTAGE MONITOR%s  poll %s%s\n' "$BOLD" "$RESET" "$LAST_POLL_TS" "$([ "$STALE" -eq 1 ] && printf ' %sstale%s' "$RED" "$RESET")" | cut -c1-"$width"
  i=0; for fn in $CONTAINERS; do sn="$(echo "$SHORTNAMES" | cut -d' ' -f$((i+1)))"; print_row "$sn" "$fn"; i=$((i+1)); done
  printf '├%s┤\n' "$bar"
  printf '│ %sHTTP %s%s  →  ' "$BOLD" "$RESET" "$STAGE_URL"
  if [ "$LAST_HTTP" = "200" ]; then col="$GREEN"; elif [ "$LAST_HTTP" = "…" ]; then col="$DIM"; else col="$RED"; fi
  printf '%s%s %ss%s  hist:%s\n' "$col" "$LAST_HTTP" "$LAST_HTTP_T" "$RESET" "$HIST"
  printf '├%s┤\n' "$bar"
  printf '│ %sWATCHTOWER-DEV (latest %d)%s\n' "$BOLD" "$LOG_LINES" "$RESET"
  for line in "${LOG_BUF[@]:-}"; do
    if printf '%s' "$line" | grep -qiE "error|rollback|unhealthy|failed=[1-9]"; then col="$RED";
    elif printf '%s' "$line" | grep -qiE "Creating|Session done"; then col="$GREEN";
    else col=""; fi
    printf '│ %s%.*s%s\n' "$col" $((width-4)) "$line" "$RESET"
  done
  [ "${#LOG_BUF[@]}" -eq 0 ] && printf '│ %s(waiting for next poll — dev interval is 5m)%s\n' "$DIM" "$RESET"
  printf '├%s┤\n' "$bar"
  printf '│ %s%s%s\n' "$bcol" "$banner" "$RESET"
  printf '└%s┘\n' "$bar"
  printf '%sq: quit%s' "$DIM" "$RESET"
}

print_once() {
  local sn fn i=0
  for fn in $CONTAINERS; do
    sn="$(echo "$SHORTNAMES" | cut -d' ' -f$((i+1)))"; i=$((i+1))
    printf '%s digest=%s health=%s last_http=%s %s hist=%s\n' \
      "$sn" "${DIGEST[$fn]:-?}" "${HEALTH[$fn]:-?}" "$LAST_HTTP" "$STAGE_URL" "$HIST"
  done
}

# --- main ---------------------------------------------------------------------
poll_docker
poll_logs
poll_http

if [ "$ONCE" -eq 1 ]; then
  UI=0; RED=""; GREEN=""; YELLOW=""; BOLD=""; DIM=""; RESET=""
  print_once
  exit 0
fi

if [ "$UI" -eq 0 ]; then
  # non-TTY: plain event stream
  print_once
  while true; do
    sleep "$INTERVAL"
    before_d="${DIGEST[leaguesphere_stage.www]}${DIGEST[leaguesphere_stage.staging-app]}"
    before_h="${HEALTH[leaguesphere_stage.www]}${HEALTH[leaguesphere_stage.staging-app]}"
    poll_docker; poll_logs
    POLL_COUNT=$((POLL_COUNT+1))
    if [ $((POLL_COUNT % (HTTP_INTERVAL / INTERVAL) )) -eq 0 ]; then poll_http; fi
    after_d="${DIGEST[leaguesphere_stage.www]}${DIGEST[leaguesphere_stage.staging-app]}"
    after_h="${HEALTH[leaguesphere_stage.www]}${HEALTH[leaguesphere_stage.staging-app]}"
    if [ "$before_d" != "$after_d" ] || [ "$before_h" != "$after_h" ]; then print_once; fi
    for line in "${LOG_BUF[@]}"; do printf 'log: %s\n' "$line"; done
    LOG_BUF=()
  done
fi

while [ "$QUIT" -eq 0 ]; do
  render
  # timed read for q key (UI mode)
  read -rsn1 -t "$INTERVAL" key 2>/dev/null || true
  [ "${key:-}" = "q" ] && QUIT=1
  poll_docker; poll_logs
  POLL_COUNT=$((POLL_COUNT+1))
  if [ $((POLL_COUNT % (HTTP_INTERVAL / INTERVAL) )) -eq 0 ]; then poll_http; fi
done
tput cnorm; clear
