#!/usr/bin/env bash
# Common helpers for amnezia-mesh. Sourced by bin/awg-mesh — not standalone.
# Bash 3.2 compatible (macOS) and POSIX-ish: no associative arrays, no mapfile.

AWG_MESH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '%s\n' "$*" >&2; }
die() { log "amnezia-mesh: error: $*"; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

# --- environment -------------------------------------------------------------

ENV_FILE="$AWG_MESH_ROOT/config/server.env"

load_env() {
  [ -f "$ENV_FILE" ] || die "not initialized: $ENV_FILE missing (run: awg-mesh init)"
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}

env_get() { # env_get KEY DEFAULT
  local key="$1" def="${2:-}" val
  val=$(grep -E "^$key=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
  [ -n "$val" ] && printf '%s' "$val" || printf '%s' "$def"
}

# --- docker-based key generation (host needs only docker) --------------------

gen_keypair() { # gen_keypair <image> -> "priv pub" on stdout
  local image="$1" priv pub
  # --entrypoint: images built with an entrypoint (e.g. the Amnezia app's own
  # container) would otherwise run it and hang instead of generating keys.
  priv=$(docker run --rm --network none --entrypoint awg "$image" genkey) \
    || die "awg genkey failed (image: $image)"
  pub=$(printf '%s' "$priv" | docker run --rm --network none --entrypoint awg -i "$image" pubkey) \
    || die "awg pubkey failed (image: $image)"
  printf '%s %s' "$priv" "$pub"
}

gen_psk() { # gen_psk <image>
  docker run --rm --network none --entrypoint awg "$1" genpsk || die "awg genpsk failed (image: $1)"
}

# Probe whether the AWG image supports I1-I5 (CPS) parameters. Tries to bring
# up a throwaway interface whose config contains an I1 line: success means the
# parser accepts it. Never fatal — result is recorded in server.env.
probe_i_support() { # probe_i_support <image> -> SUPPORTED | UNSUPPORTED | NO_AWGQUICK
  local image="$1"
  docker run --rm --network none --device /dev/net/tun:/dev/net/tun --entrypoint sh "$image" -c '
    command -v awg-quick >/dev/null 2>&1 || { echo NO_AWGQUICK; exit 0; }
    d=$(mktemp -d)
    priv=$(awg genkey)
    printf "[Interface]\nPrivateKey = %s\nAddress = 10.213.0.1/30\nListenPort = 23199\nI1 = 30-50\n[Peer]\nPublicKey = %s\nAllowedIPs = 10.213.0.2/32\n" "$priv" "$priv" > "$d/p.conf"
    if awg-quick up "$d/p.conf" >/dev/null 2>&1; then
      awg-quick down "$d/p.conf" >/dev/null 2>&1
      echo SUPPORTED
    else
      echo UNSUPPORTED
    fi
    rm -rf "$d"
  '
}

# --- peer db -----------------------------------------------------------------

PEERS_DB="$AWG_MESH_ROOT/config/peers.db"

next_free_ip() { # next_free_ip <subnet> -> first free host IP (hub=.1 is reserved)
  python3 - "$1" "$PEERS_DB" <<'PY'
import ipaddress, sys
net = ipaddress.ip_network(sys.argv[1])
used = set()
try:
    with open(sys.argv[2]) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                used.add(ipaddress.ip_address(parts[1]))
except FileNotFoundError:
    pass
hosts = list(net.hosts())
for ip in hosts[1:]:  # skip .0 network and .1 hub
    if ip not in used:
        print(ip)
        sys.exit(0)
PY
}

valid_name() { # DNS-label-ish peer names: lowercase, digits, dash, 1..32 chars
  [ -n "$1" ] && [ "${#1}" -le 32 ] || return 1
  case "$1" in *[!a-z0-9-]*) return 1 ;; esac
  return 0
}

# --- compose with server.env interpolated ------------------------------------

compose() {
  ( set -a; . "$ENV_FILE"; set +a; cd "$AWG_MESH_ROOT" && docker compose "$@" )
}

confirm() { # confirm <question> -> 0/1; auto-yes when NONINTERACTIVE=1
  [ "${AWG_MESH_NONINTERACTIVE:-0}" = "1" ] && return 0
  printf '%s [y/N] ' "$*" >&2
  local ans
  read -r ans
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
