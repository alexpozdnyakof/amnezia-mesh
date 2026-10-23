# amnezia-mesh

Self-hosted WireGuard mesh with AmneziaWG traffic obfuscation, MagicDNS and
Tailscale-style exit/mesh profiles — on a single VPS, in ~10 minutes, with no
dependencies beyond Docker.

Think "your own Tailscale", but you own every hop: one small server, the
official Amnezia app on your devices, and no coordination servers, no accounts,
no third-party relays.

## Features

- **CGNAT mesh network** (`100.64.0.0/24`, RFC 6598) — every device gets a
  stable IP; SSH/ping between devices work through the hub, like `tailscale ssh`.
- **AmneziaWG 3.1 obfuscation** — junk-packet handshakes, header type
  substitution, header protection key, random padding/trailers. Parameters are
  **randomized per deployment**, so DPI fingerprints differ between installs.
- **MagicDNS** — dnsmasq on the hub answers `<device>.<domain>` (e.g.
  `laptop.awg`) and forwards everything else to your upstream resolver through
  the tunnel.
- **Exit + mesh profiles per device** — `exit` routes all traffic through the
  VPS (censorship circumvention); `mesh` routes only the CGNAT subnet, leaving
  the internet direct. Both are generated for every device.
- **Native Amnezia app profiles** (`vpn://`) plus plain `.conf` for any
  awg/wg-compatible client.
- **Version-agnostic by design** — the AWG image is an external, replaceable
  dependency; all logic lives on the host (see *Design* below).
- **Agent-friendly CLI** — every command has `--json` output, env-var
  overrides and a non-interactive mode.

## Requirements

- A VPS with a public IP, Docker with the compose plugin, and `python3`
  (>= 3.8, standard library only — no `pip install`).
- UDP port open in the VPS firewall (443/udp recommended — it blends into
  QUIC-looking traffic and is the hardest for ISPs to shape).

## Quickstart (human)

```sh
git clone https://github.com/<you>/amnezia-mesh && cd amnezia-mesh

./bin/awg-mesh init --host YOUR_IP_OR_DOMAIN --port 443
./bin/awg-mesh peer add laptop
# → prints: config/peers/laptop-exit.vpn, laptop-mesh.vpn, plus .conf variants
# import the .vpn link into the Amnezia app on the device

./bin/awg-mesh peer add phone
./bin/awg-mesh doctor      # post-install self-checks
./bin/awg-mesh monitoring install   # optional: cron stats + watchdog
```

On the device: Amnezia app → import the `vpn://` link → connect. Devices can
now reach each other by IP (`100.64.0.x`) or name (`phone.awg`).

## Quickstart (agent / automation)

```sh
export AWG_MESH_NONINTERACTIVE=1
./bin/awg-mesh --json init --host 198.51.100.10 --port 443
./bin/awg-mesh --json peer add laptop
./bin/awg-mesh --json doctor        # exit code 0 = all checks green
```

Output is a single JSON object per command; failures set a non-zero exit code
and `{"ok": false, "error": "..."}`.

## Commands

| Command | Description |
|---|---|
| `awg-mesh init [--host H] [--port P] [--subnet CIDR] [--image IMG] [--domain D] [--rdp-reject]` | Generate keys + random obfuscation, render configs, start containers |
| `awg-mesh peer add <name> [--type exit\|mesh\|both]` | New device: keys, IP, profiles (applied via `awg syncconf`, then the awg container is restarted — syncconf alone can silently wedge fresh handshakes in the userspace daemon) |
| `awg-mesh peer list` | Devices, IPs, creation dates |
| `awg-mesh peer revoke <name>` | Remove device (config applied, profiles deleted) |
| `awg-mesh doctor [--json]` | Docker, containers, listen port, ip_forward, MagicDNS, port publishing |
| `awg-mesh monitoring install\|uninstall` | Cron stats (`/var/log/amnezia-mesh-stats.log`) + watchdog |
| `awg-mesh adopt (--container C \| --config F --image IMG) --host H [--port P] [--dns1 D] [--dns2 D] [--rdp-reject]` | Migrate an existing AmneziaWG server under awg-mesh management (see below) |

## Adopting an existing server

You already run AmneziaWG (a container or a hand-made deployment) and want
`awg-mesh` management — peer management, MagicDNS, doctor, monitoring —
**without reissuing a single client profile**.

```sh
./bin/awg-mesh adopt --container amnezia-awg --host YOUR_IP --port 443
# or, from a config file on the host:
./bin/awg-mesh adopt --config /root/awg0.conf --image amneziavpn/amneziawg-go:latest \
    --host YOUR_IP --port 443
```

What is carried over **verbatim** (so clients never notice):

| | after adopt |
|---|---|
| server private key | same — clients see the same server |
| obfuscation profile (Jc/Jmin/Jmax/S/H, HeaderProtectionKey, timers) | same — DPI fingerprint unchanged |
| peer public keys, PSKs | same |
| peer IPs | same — taken from each peer's `AllowedIPs` |
| client profiles on devices | keep working, no reissue |

What changes: the container is recreated under the `amnezia-mesh` compose
project (renamed to `amnezia-mesh-awg`, dnsmasq becomes a sidecar) and the
deployment is managed by `awg-mesh` from then on. Optional knobs that an
`awg0.conf` cannot express are flags: `--dns1/--dns2` (upstream resolvers for
MagicDNS forwarding, default 1.1.1.1), `--rdp-reject` (RDP UDP/3389 reject
rule), `--domain` (default `awg`).

Step by step, `adopt`:

1. reads `awg0.conf` — from inside the container (`--container`, image is
   detected automatically) or from a file (`--config`, `--image` required);
2. parses `[Interface]` + `[Peer]` sections into `config/server.env` +
   `config/peers.db` — refusing (with the offending key listed) rather than
   dropping anything it doesn't understand;
3. renders `awg0.conf` / `dnsmasq.conf` / `start.sh` and starts the stack;
4. if `--container`: **stops** the old container (never removes it) and runs
   `doctor`; on failure it rolls back automatically — restarts the old
   container, nothing deleted.

Safety rules:

- the old container is only stopped and stays on the host as the rollback
  plan: `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <old>`
- adopt aborts on unknown `[Interface]` keys, a server `Address` that is not
  the subnet's first host, or peers without `PublicKey`/`PresharedKey`;
- peer names come from `# name (added …)` comments; unnamed peers get a
  generated `peer-xxxxxx` name, collisions get `-2` suffixes.

## Design: why AmneziaWG version updates don't matter

1. **The AWG image is a plain dependency.** `docker-compose.yml` references
   `amneziavpn/amneziawg-go` (override with `--image` or `AWG_MESH_IMAGE`).
   Nothing is forked or patched; swapping the image tag needs no project
   changes.
2. **All logic lives on the host.** The server config, dnsmasq config and the
   container entrypoint (iptables bootstrap: forwarding, MASQUERADE, MSS clamp,
   optional RDP-UDP reject) are generated into `config/` and bind-mounted.
   Recreating or upgrading the container loses nothing.
3. **The interface is the stable UAPI.** `awg0.conf` parameters (Jc/S/H,
   HeaderProtectionKey, timers) are part of the AWG protocol and don't change
   across releases. Experimental `I1`–`I5` (CPS) parameters are probed at
   `init` time; the project records support and stays compatible either way.
4. **Profiles are the app's native format.** `vpn://` profiles are
   byte-compatible with what the official Amnezia app exports
   (`base64url(uint32_be(len) + zlib(json, 9))`, compact separators — verified
   byte-identical). New app releases keep importing them.

## Layout

```
docker-compose.yml      awg container + dnsmasq sidecar (shared netns)
bin/awg-mesh            CLI entrypoint (thin shim, runs from the checkout)
awg_mesh/               python package: cli, envfile, peers, keygen, compose,
                        render, profile, doctor, adopt (stdlib only)
scripts/                optional monitoring (stats, watchdog, cron)
tests/                  pytest suite: render golden files, peers db + flock,
                        profile codec roundtrip
config/                 generated secrets + state — gitignored, stays on host
```

## How the mesh works (30 seconds)

WireGuard is cryptokey routing: each packet is encrypted to a peer's public
key, and `AllowedIPs` maps destination IPs to peers. A phone pinging
`100.64.0.4` encrypts to the **hub's** key — it never learns the macbook's real
address. The hub decrypts, re-encrypts to the macbook's key, and forwards.
This is hub-and-spoke (routed mesh), not P2P: it works behind any NAT,
including carrier-grade mobile NATs where hole punching is useless.
`PersistentKeepalive=25` on both sides keeps NAT mappings alive so devices are
mutually reachable.

## Hardening notes

- `config/` contains private keys — it is gitignored, mode 600, and never
  leaves the server. Back it up encrypted if you rebuild the VPS.
- Keep the VPS firewall default-deny; allow only SSH and your chosen UDP port
  (443/udp blends best with normal HTTPS/QUIC traffic).
- Obfuscation defeats DPI **fingerprints**, not traffic volume analysis. It
  is not a substitute for Tor when facing a global passive adversary.
- `--rdp-reject` helps RDP over the tunnel (forces instant TCP fallback of the
  UDP graphics channel). Enable it in `init` if you RDP through the mesh.

## Troubleshooting

| Symptom | Check |
|---|---|
| Device won't connect | `awg-mesh doctor`; VPS firewall allows the UDP port |
| Long "connecting", then "connected" but no internet | Almost always the wrong/stale profile on the device: check which profile is active in the app and delete old/test ones |
| Domains don't resolve on device | `doctor` magicdns check; device profile must use hub DNS (generated profiles do) |
| Slow throughput | MTU is 1280 by design (headroom for padding); check `steal`/CPU on small VPS plans |
| `Protocol not supported` from `awg` CLI | known amneziawg-tools quirk on single-key queries; use full `awg show` — cosmetic only |

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

The suite needs no Docker and no network: server config rendering is diffed
byte-for-byte against golden files produced by the original implementation,
the peers db is hammered concurrently to prove `flock` serialization, and the
`vpn://` codec is roundtrip-tested.

## License

MIT
