#!/usr/bin/env bash
#
# Provision the Oracle Always Free A1 instance that mirrors codey.lehel.xyz.
#
# Idempotent: every resource is looked up by display name first, so re-running
# attaches to what already exists instead of creating duplicates.
#
# Stays strictly inside the Always Free allowance (4 OCPU / 24 GB RAM /
# 200 GB block storage total), so it costs nothing even on a pay-as-you-go
# tenancy. Defaults use half the allowance and leave the other half free.
#
#   ./provision-oracle-codey.sh          # create (or attach to) everything
#   ./provision-oracle-codey.sh --status # print what exists, change nothing
#
set -euo pipefail

PROFILE=${OCI_CONFIG_PROFILE:-OCI_FREE}
CONFIG=${OCI_CONFIG_FILE:-$HOME/.oci/config}
REGION=${OCI_REGION:-eu-frankfurt-1}

NAME=${NAME:-oracle-codey}
VCN_NAME=${VCN_NAME:-oracle-codey-vcn}
SUBNET_NAME=${SUBNET_NAME:-oracle-codey-subnet}
VCN_CIDR=${VCN_CIDR:-10.0.0.0/16}
SUBNET_CIDR=${SUBNET_CIDR:-10.0.1.0/24}

SHAPE=${SHAPE:-VM.Standard.A1.Flex}
OCPUS=${OCPUS:-2}
MEMORY_GB=${MEMORY_GB:-12}
BOOT_GB=${BOOT_GB:-100}
SSH_PUB=${SSH_PUB:-$HOME/.ssh/id_rsa.pub}

# Canonical Ubuntu 24.04 aarch64. Resolved per region; override if it rotates.
IMAGE=${IMAGE:-ocid1.image.oc1.eu-frankfurt-1.aaaaaaaast7orcavt5xwy6jkkebtl4o2il34umu5gomppawzlabv6ejgom7a}

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
    local vnic v6
    vnic=$(oci_cli compute instance list-vnics --instance-id "$i" \
      --output json | jq -r '.data[0].id // empty')
    v6=$(oci_cli raw-request --http-method GET \
      --target-uri "https://iaas.$REGION.oraclecloud.com/20160918/ipv6?vnicId=$vnic" \
      --output json | jq -r '.data[0].ipAddress // empty')
    printf 'public ip6   %s\n' "${v6:-<none>}"
    oci_cli compute instance get --instance-id "$i" --output json |
      jq -r '.data | "state        \(."lifecycle-state")\nshape        \(.shape) \(."shape-config".ocpus // "")ocpu \(."shape-config"."memory-in-gbs" // "")GB"'
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

AD=$(oci_cli iam availability-domain list --output json |
  jq -r '.data[0].name')
[[ -z "$AD" ]] && { echo "FATAL: could not resolve an availability domain" >&2; exit 1; }

# ---------------------------------------------------------------- network

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

# ---------------------------------------------------------------- ipv6 (VCN)

# The VCN is IPv4-only when created. IPv6 is a separate, additive prefix:
# Oracle allocates a /56 (or you bring your own). Without it there is no subnet
# /64 to hand out and no ::/0 route to write, so this has to come first.
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

# A /56 fixes the first two hex digits of the 4th hextet and leaves the last
# two free, so subnet n is <h1>:<h2>:<h3>:<h4[0:2]>NN::/64. We always claim 01.
read -r V6_H1 V6_H2 V6_H3 V6_H4 <<<"$(echo "${V6_PREFIX%%::*}" | tr ':' ' ')"
V6_SUBNET="${V6_H1}:${V6_H2}:${V6_H3}:${V6_H4:0:2}01::/64"
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
# A fresh VCN ships a default route table with NO rules. Both families need a
# default route: 0.0.0.0/0 and ::/0. Rebuild the two gateway routes on every run
# while preserving any other rule someone added, so re-running never strips
# IPv6 routing.
log "ensuring 0.0.0.0/0 and ::/0 -> igw in the route table"
RT_RULES=$(oci_cli network route-table get --rt-id "$RT" --output json | jq -c --arg igw "$IGW" '
  [(.data."route-rules" // [])[]
     | select(.destination != "0.0.0.0/0" and .destination != "::/0")]
  + [{destination:"0.0.0.0/0", destinationType:"CIDR_BLOCK", networkEntityId:$igw},
     {destination:"::/0",        destinationType:"CIDR_BLOCK", networkEntityId:$igw}]')
oci_cli network route-table update --rt-id "$RT" --force \
  --route-rules "$RT_RULES" --wait-for-state AVAILABLE >/dev/null

SL=$(oci_cli network security-list list --compartment-id "$TENANCY" \
  --vcn-id "$VCN" --output json | jq -r '.data[0].id // empty')
# The default security list opens only 22. Set the exact rule set every run:
# Traefik needs 80/443 in both families, and ICMPv6 (protocol 58) is not
# optional — it carries neighbour and path-MTU discovery, so leaving it out
# gives connections that hang on larger responses instead of failing cleanly.
log "ensuring security list: 22/80/443 v4+v6, ICMPv6, egress all"
oci_cli network security-list update --security-list-id "$SL" --force \
  --ingress-security-rules '[
    {"protocol":"6","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":80,"max":80}}},
    {"protocol":"6","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}},
    {"protocol":"6","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":80,"max":80}}},
    {"protocol":"6","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}},
    {"protocol":"58","source":"::/0","sourceType":"CIDR_BLOCK","isStateless":false},
    {"protocol":"1","source":"0.0.0.0/0","sourceType":"CIDR_BLOCK","isStateless":false}
  ]' \
  --egress-security-rules '[
    {"protocol":"all","destination":"0.0.0.0/0","destinationType":"CIDR_BLOCK","isStateless":false},
    {"protocol":"all","destination":"::/0","destinationType":"CIDR_BLOCK","isStateless":false}
  ]' >/dev/null

SUBNET=$(subnet_id "$VCN")
if [[ -z "$SUBNET" ]]; then
  log "creating subnet $SUBNET_NAME ($SUBNET_CIDR)"
  SUBNET=$(oci_cli network subnet create --compartment-id "$TENANCY" \
    --vcn-id "$VCN" --cidr-block "$SUBNET_CIDR" --display-name "$SUBNET_NAME" \
    --route-table-id "$RT" --security-list-ids "[\"$SL\"]" \
    --wait-for-state AVAILABLE --output json | jq -r '.data.id')
fi

# The subnet also starts IPv4-only; it needs its own /64 before any VNIC can
# hold an address. Must lie inside the VCN's /56.
CUR6=$(oci_cli network subnet get --subnet-id "$SUBNET" --output json |
  jq -r '.data."ipv6-cidr-block" // empty')
if [[ -z "$CUR6" ]]; then
  log "adding IPv6 $V6_SUBNET to the subnet"
  oci_cli network subnet add-ipv6-subnet-cidr --subnet-id "$SUBNET" \
    --ipv6-cidr-block "$V6_SUBNET" --wait-for-state SUCCEEDED >/dev/null
else
  log "subnet IPv6 already present: $CUR6"
fi

# ---------------------------------------------------------------- instance

INST=$(instance_id)
if [[ -z "$INST" ]]; then
  log "launching $NAME ($SHAPE ${OCPUS}ocpu/${MEMORY_GB}GB, ${BOOT_GB}GB boot) in $AD"
  INST=$(oci_cli compute instance launch --compartment-id "$TENANCY" \
    --availability-domain "$AD" --shape "$SHAPE" \
    --shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEMORY_GB}" \
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

# Assign an IPv6 to the instance's primary VNIC. `oci network vnic assign-ipv6`
# is broken in oci-cli 3.96.x: it passes hostname= to an SDK method that has no
# such parameter ("TypeError: assign_ipv6() got an unexpected keyword argument
# 'hostname'"), and the SDK exposes create_ipv6 instead of assign_ipv6. The
# REST call does work, so use raw-request rather than a python one-liner.
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
if [[ -n "$V6_ADDR" ]]; then
  printf '\nIPv6 needs the address pinned in the OS — OCI delivers it by router\n'
  printf 'advertisement, but Docker sets forwarding=1 which leaves accept_ra=0,\n'
  printf 'so the RA address and default route expire and never return. Set them\n'
  printf 'statically (ansible: system.ipv6), gateway = router EUI-64 link-local.\n'
fi
