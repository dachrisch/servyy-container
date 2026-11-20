#!/usr/bin/env bash
#
# Provision the Oracle Always Free E2.1.Micro (amd64) instance that runs the
# `runny` Forgejo Actions runner.
#
# Modeled on scripts/provision-oracle-codey.sh (same VCN, same lookup-by-name
# idempotency), but adapted for the Micro:
#   * fixed shape (1 OCPU / 1 GB) — no --shape-config;
#   * SSH-only ingress (the runner only dials OUT), plus a source-scoped :9100
#     so servy's Prometheus can scrape node-exporter and nothing else;
#   * Ubuntu 24.04 minimal amd64 (resolved at runtime, overridable via IMAGE).
#
#   ./provision-oracle-runner.sh          # create (or attach to) everything
#   ./provision-oracle-runner.sh --status # print what exists, change nothing
#
set -euo pipefail

PROFILE=${OCI_CONFIG_PROFILE:-OCI_FREE}
CONFIG=${OCI_CONFIG_FILE:-$HOME/.oci/config}
REGION=${OCI_REGION:-eu-frankfurt-1}

NAME=${NAME:-oracle-runner}
# The runner lives in codey's VCN (the plan's "same VCN"). Override VCN_NAME to
# provision a dedicated VCN instead.
VCN_NAME=${VCN_NAME:-oracle-codey-vcn}
SUBNET_NAME=${SUBNET_NAME:-oracle-runner-subnet}
VCN_CIDR=${VCN_CIDR:-10.0.0.0/16}
SUBNET_CIDR=${SUBNET_CIDR:-10.0.2.0/24}

SHAPE=${SHAPE:-VM.Standard.E2.1.Micro}
BOOT_GB=${BOOT_GB:-50}
SSH_PUB=${SSH_PUB:-$HOME/.ssh/id_rsa.pub}

# servy's Prometheus (Hetzner), the only source allowed to scrape node-exporter.
SERVY_V4=${SERVY_V4:-49.13.6.173}
SERVY_V6=${SERVY_V6:-2a01:4f8:c013:f6f4::1}

# Ubuntu minimal amd64 (UBUNTU_VERSION, default 26.04 like codey). Empty by default: resolved at runtime from the
# image catalogue. Pin it (like codey pins 26.04) once the OCID is known.
IMAGE=${IMAGE:-}

log() { printf '\n=== %s\n' "$*"; }

# Read a key from the chosen profile in ~/.oci/config.
cfg() {
  awk -v s="[$PROFILE]" -v key="$1" '
    $0 == s { inside = 1; next }
    /^\[/ { inside = 0 }
    inside && index($0, key "=") == 1 { sub("^" key "=", ""); print; exit }
  ' "$CONFIG"
}

TENANCY=$(cfg tenancy)
if [[ -z "$TENANCY" ]]; then
  echo "FATAL: no tenancy in $CONFIG under profile [$PROFILE]" >&2
  exit 1
fi

oci_cli() { command oci --profile "$PROFILE" --region "$REGION" "$@"; }

# ---------------------------------------------------------------- lookups

vcn_id() {
  oci_cli network vcn list --compartment-id "$TENANCY" \
    --display-name "$VCN_NAME" --lifecycle-state AVAILABLE --output json |
    jq -r '.data[0].id // empty'
}

subnet_id() {
  oci_cli network subnet list --compartment-id "$TENANCY" \
    --vcn-id "$1" --display-name "$SUBNET_NAME" --lifecycle-state AVAILABLE \
    --output json | jq -r '.data[0].id // empty'
}

instance_id() {
  oci_cli compute instance list --compartment-id "$TENANCY" \
    --display-name "$NAME" --output json |
    jq -r '[.data[] | select(."lifecycle-state" != "TERMINATED")][0].id // empty'
}

public_ip() {
  oci_cli compute instance list-vnics --instance-id "$1" --output json |
    jq -r '.data[0]."public-ip" // empty'
}

# Latest Ubuntu ${UBUNTU_VERSION} minimal image that is compatible with the
# (amd64) shape. Filtering by --shape excludes the aarch64 builds.
UBUNTU_VERSION=${UBUNTU_VERSION:-26.04}
image_id() {
  oci_cli compute image list --compartment-id "$TENANCY" \
    --operating-system "Canonical Ubuntu" \
    --shape "$SHAPE" --sort-by TIMECREATED --sort-order DESC --all --output json |
    jq -r --arg v "$UBUNTU_VERSION" \
      '[.data[] | select(."display-name" | startswith("Canonical-Ubuntu-" + $v + "-Minimal-"))][0].id // empty'
}

status() {
  local v s i ip
  v=$(vcn_id); s=""; i=$(instance_id)
  [[ -n "$v" ]] && s=$(subnet_id "$v")
  log "status"
  printf 'profile      %s\n' "$PROFILE"
  printf 'region       %s\n' "$REGION"
  printf 'vcn          %s\n' "${v:-<absent>}"
  printf 'subnet       %s\n' "${s:-<absent>}"
  printf 'instance     %s\n' "${i:-<absent>}"
  if [[ -n "$i" ]]; then
    ip=$(public_ip "$i")
    printf 'public ip    %s\n' "${ip:-<none>}"
    oci_cli compute instance get --instance-id "$i" --output json |
      jq -r '.data | "state        \(."lifecycle-state")\nshape        \(.shape)"'
  fi
}

if [[ "${1:-}" == "--status" ]]; then
  status
  exit 0
fi

# ---------------------------------------------------------------- prerequisites

if [[ ! -f "$SSH_PUB" ]]; then
  echo "FATAL: SSH public key not found: $SSH_PUB" >&2
  echo "       ssh-keygen -t ed25519 -N '' -f ${SSH_PUB%.pub}" >&2
  exit 1
fi

# The Always Free Micro is only offered in one availability domain per
# tenancy, so pick the first AD whose shape list contains it.
AD=""
for ad in $(oci_cli iam availability-domain list --output json | jq -r '.data[].name'); do
  if oci_cli compute shape list --compartment-id "$TENANCY" --availability-domain "$ad" \
       --all --output json | jq -e --arg s "$SHAPE" 'any(.data[]; .shape == $s)' >/dev/null; then
    AD=$ad; break
  fi
done
[[ -z "$AD" ]] && { echo "FATAL: no availability domain offers $SHAPE" >&2; exit 1; }

# ---------------------------------------------------------------- network

# Attach to codey's VCN (or create a dedicated one if VCN_NAME was overridden
# to a name that does not exist yet).
VCN=$(vcn_id)
if [[ -z "$VCN" ]]; then
  log "creating VCN $VCN_NAME ($VCN_CIDR)"
  DNS_LABEL=$(printf '%s' "$VCN_NAME" | tr -cd 'a-z0-9' | cut -c1-15)
  VCN=$(oci_cli network vcn create --compartment-id "$TENANCY" \
    --cidr-blocks "[\"$VCN_CIDR\"]" --display-name "$VCN_NAME" \
    --dns-label "$DNS_LABEL" \
    --wait-for-state AVAILABLE --output json | jq -r '.data.id')
else
  log "VCN already present: $VCN"
fi

# codey's script already allocates the VCN's /56 and writes the ::/0 route, so
# when reusing codey's VCN this is a no-op. Keep the block so a dedicated VCN
# still gets IPv6 + routing (mirrors provision-oracle-codey.sh).
V6_PREFIX=$(oci_cli network vcn get --vcn-id "$VCN" --output json |
  jq -r '.data."ipv6-cidr-blocks"[0] // empty')
if [[ -z "$V6_PREFIX" ]]; then
  log "allocating an IPv6 /56 for the VCN"
  oci_cli network vcn add-ipv6-vcn-cidr --vcn-id "$VCN" \
    --is-oracle-gua-allocation-enabled true --wait-for-state SUCCEEDED >/dev/null
  V6_PREFIX=$(oci_cli network vcn get --vcn-id "$VCN" --output json |
    jq -r '.data."ipv6-cidr-blocks"[0] // empty')
  [[ -z "$V6_PREFIX" ]] && { echo "FATAL: IPv6 prefix did not appear" >&2; exit 1; }
else
  log "VCN IPv6 prefix already present: $V6_PREFIX"
fi

read -r V6_H1 V6_H2 V6_H3 V6_H4 <<<"$(echo "${V6_PREFIX%%::*}" | tr ':' ' ')"
# codey claims 01, so the runner subnet claims 02.
V6_SUBNET="${V6_H1}:${V6_H2}:${V6_H3}:${V6_H4:0:2}02::/64"
log "subnet IPv6 will be $V6_SUBNET"

IGW=$(oci_cli network internet-gateway list --compartment-id "$TENANCY" \
  --vcn-id "$VCN" --output json | jq -r '.data[0].id // empty')
if [[ -z "$IGW" ]]; then
  log "creating internet gateway"
  IGW=$(oci_cli network internet-gateway create --compartment-id "$TENANCY" \
    --vcn-id "$VCN" --is-enabled true --display-name "${VCN_NAME}-igw" \
    --wait-for-state AVAILABLE --output json | jq -r '.data.id')
fi

RT=$(oci_cli network route-table list --compartment-id "$TENANCY" \
  --vcn-id "$VCN" --output json | jq -r '.data[0].id // empty')
log "ensuring 0.0.0.0/0 and ::/0 -> igw in the route table"
RT_RULES=$(oci_cli network route-table get --rt-id "$RT" --output json | jq -c --arg igw "$IGW" '
  [(.data."route-rules" // [])[]
     | select(.destination != "0.0.0.0/0" and .destination != "::/0")]
  + [{destination:"0.0.0.0/0", destinationType:"CIDR_BLOCK", networkEntityId:$igw},
     {destination:"::/0",        destinationType:"CIDR_BLOCK", networkEntityId:$igw}]')
# The route table is shared with codey: only write it when a default route is
# actually missing, never rewrite it on a re-run.
if oci_cli network route-table get --rt-id "$RT" --output json | jq -e --arg igw "$IGW" '
     [(.data."route-rules" // [])[] | select(."network-entity-id" == $igw) | .destination]
     | (index("0.0.0.0/0") != null) and (index("::/0") != null)' >/dev/null; then
  log "route table already routes 0.0.0.0/0 and ::/0 to the igw"
else
  oci_cli network route-table update --rt-id "$RT" --force \
    --route-rules "$RT_RULES" --wait-for-state AVAILABLE >/dev/null
fi

# The runner only dials OUT, so its security list is SSH-only — plus a
# source-scoped :9100 for servy's Prometheus to scrape node-exporter. No
# 80/443 (runny has no Traefik). ICMPv6 (protocol 58) stays for neighbour and
# path-MTU discovery.
#
# A DEDICATED security list, attached only to the runner subnet. Never touch
# the VCN's default list: codey's subnet uses it, and rewriting it to SSH-only
# would drop 80/443 for code.lehel.xyz, monitor.lehel.xyz and loki.lehel.xyz.
SL_NAME=${SL_NAME:-oracle-runner-sl}
SL=$(oci_cli network security-list list --compartment-id "$TENANCY" \
  --vcn-id "$VCN" --display-name "$SL_NAME" --lifecycle-state AVAILABLE \
  --output json | jq -r '.data[0].id // empty')
SL_INGRESS='[
    {"protocol":"6","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"'$SERVY_V4'/32","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":9100,"max":9100}}},
    {"protocol":"6","source":"'$SERVY_V6'/128","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":9100,"max":9100}}},
    {"protocol":"58","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false},
    {"protocol":"1","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false}
  ]'
SL_EGRESS='[
    {"protocol":"all","destination":"0.0.0.0/0","destinationType":"CIDR_BLOCK","isStateless":false},
    {"protocol":"all","destination":"::/0","destinationType":"CIDR_BLOCK","isStateless":false}
  ]'
if [[ -z "$SL" ]]; then
  log "creating dedicated security list $SL_NAME (SSH + 9100 from servy)"
  SL=$(oci_cli network security-list create --compartment-id "$TENANCY" \
    --vcn-id "$VCN" --display-name "$SL_NAME" \
    --ingress-security-rules "$SL_INGRESS" --egress-security-rules "$SL_EGRESS" \
    --wait-for-state AVAILABLE --output json | jq -r '.data.id')
else
  log "ensuring rules on $SL_NAME"
  oci_cli network security-list update --security-list-id "$SL" --force \
    --ingress-security-rules "$SL_INGRESS" --egress-security-rules "$SL_EGRESS" >/dev/null
fi

SUBNET=$(subnet_id "$VCN")
if [[ -z "$SUBNET" ]]; then
  log "creating subnet $SUBNET_NAME ($SUBNET_CIDR)"
  SUBNET=$(oci_cli network subnet create --compartment-id "$TENANCY" \
    --vcn-id "$VCN" --cidr-block "$SUBNET_CIDR" --display-name "$SUBNET_NAME" \
    --route-table-id "$RT" --security-list-ids "[\"$SL\"]" \
    --wait-for-state AVAILABLE --output json | jq -r '.data.id')
fi

CUR6=$(oci_cli network subnet get --subnet-id "$SUBNET" --output json |
  jq -r '.data."ipv6-cidr-block" // empty')
if [[ -z "$CUR6" ]]; then
  log "adding IPv6 $V6_SUBNET to the subnet"
  oci_cli network subnet add-ipv6-subnet-cidr --subnet-id "$SUBNET" \
    --ipv6-cidr-block "$V6_SUBNET" --wait-for-state SUCCEEDED >/dev/null
else
  log "subnet IPv6 already present: $CUR6"
fi

# ---------------------------------------------------------------- image

if [[ -z "$IMAGE" ]]; then
  IMAGE=$(image_id)
fi
if [[ -z "$IMAGE" ]]; then
  echo "FATAL: could not resolve an Ubuntu $UBUNTU_VERSION minimal image for $SHAPE; set IMAGE=…" >&2
  exit 1
fi
log "image $IMAGE"

# ---------------------------------------------------------------- instance

INST=$(instance_id)
if [[ -z "$INST" ]]; then
  log "launching $NAME ($SHAPE, ${BOOT_GB}GB boot) in $AD"
  # E2.1.Micro is a FIXED shape: no --shape-config (the Micro has 1 OCPU / 1 GB
  # by definition, unlike the A1.Flex codey script drives with ocpus/memory).
  INST=$(oci_cli compute instance launch --compartment-id "$TENANCY" \
    --availability-domain "$AD" --shape "$SHAPE" \
    --image-id "$IMAGE" --subnet-id "$SUBNET" --assign-public-ip true \
    --display-name "$NAME" --boot-volume-size-in-gbs "$BOOT_GB" \
    --metadata "{\"ssh_authorized_keys\":\"$(tr -d '\n' < "$SSH_PUB")\"}" \
    --wait-for-state RUNNING --output json | jq -r '.data.id')
else
  log "instance already present: $INST"
  STATE=$(oci_cli compute instance get --instance-id "$INST" --output json |
    jq -r '.data."lifecycle-state"')
  if [[ "$STATE" != "RUNNING" ]]; then
    log "starting instance (state was $STATE)"
    oci_cli compute instance action --instance-id "$INST" --action START \
      --wait-for-state RUNNING >/dev/null
  fi
fi

# ---------------------------------------------------------------- ipv6 (VNIC)

VNIC=$(oci_cli compute instance list-vnics --instance-id "$INST" \
  --output json | jq -r '.data[0].id // empty')
V6_ENDPOINT="https://iaas.$REGION.oraclecloud.com/20160918/ipv6"
V6_ADDR=$(oci_cli raw-request --http-method GET \
  --target-uri "$V6_ENDPOINT?vnicId=$VNIC" --output json |
  jq -r '.data[0].ipAddress // empty')
if [[ -z "$V6_ADDR" ]]; then
  log "assigning an IPv6 address to the instance VNIC"
  oci_cli raw-request --http-method POST --target-uri "$V6_ENDPOINT" \
    --request-body "{\"vnicId\":\"$VNIC\",\"ipv6SubnetCidr\":\"$V6_SUBNET\",\"lifetime\":\"RESERVED\"}" \
    >/dev/null
  V6_ADDR=$(oci_cli raw-request --http-method GET \
    --target-uri "$V6_ENDPOINT?vnicId=$VNIC" --output json |
    jq -r '.data[0].ipAddress // empty')
else
  log "VNIC IPv6 already present: $V6_ADDR"
fi

IP=$(public_ip "$INST")
log "done"
printf 'instance   %s\n' "$INST"
printf 'public ip  %s\n' "${IP:-<pending>}"
printf 'public ip6 %s\n' "${V6_ADDR:-<none>}"
printf 'ssh        ssh -i %s ubuntu@%s\n' "${SSH_PUB%.pub}" "${IP:-<ip>}"
printf '\nNext: create the runny.lehel.xyz A/AAAA record (dns-master) pointing at the\n'
printf 'IPs above, then `ansible-playbook servyy.yml -i production -l runny.lehel.xyz -u ubuntu`\n'
printf 'and `./servyy.sh --limit runny.lehel.xyz --tags user.docker.runny`.\n'
