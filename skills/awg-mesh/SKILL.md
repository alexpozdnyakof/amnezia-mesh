---
name: awg-mesh
description: "Set up and operate a self-hosted WireGuard mesh with AmneziaWG obfuscation, MagicDNS and exit/mesh profiles on a single VPS. Use when the user wants to create their own VPN/mesh (a Tailscale alternative they fully own), add or remove devices, migrate/adopt an existing AmneziaWG server, or troubleshoot VPN connectivity (no handshake, DNS, MTU/slowness). Ships inside the awg-mesh CLI: `awg-mesh skill` prints this file, `awg-mesh skill --install` puts it where coding agents find it."
---

# awg-mesh operations

`awg-mesh` is a CLI that turns one VPS into an obfuscated WireGuard hub:
every device gets a stable CGNAT IP (`100.64.0.x`) and a MagicDNS name
(`<device>.awg`), devices reach each other through the hub, and each device
gets AmneziaWG-obfuscated profiles (`vpn://` for the Amnezia app, `.conf`
for any awg/wg client).

Requirements: a VPS with a public IP, Docker with the compose plugin, and
this CLI. Nothing else — no coordination server, no accounts, no relays.

## Install the CLI

```sh
# Go build (darwin/linux, amd64/arm64) — preferred
brew tap alexpozdnyakof/tap
brew install --cask alexpozdnyakof/tap/awg-mesh

# or the Python version (stdlib only, needs python3 >= 3.8):
git clone https://github.com/alexpozdnyakof/amnezia-mesh && cd amnezia-mesh
./bin/awg-mesh --version
```

## First deploy (one VPS, ~10 minutes)

```sh
awg-mesh init --host YOUR_IP_OR_DOMAIN --port 443
awg-mesh peer add laptop        # writes config/peers/laptop-{exit,mesh}.vpn + .conf
awg-mesh peer add phone
awg-mesh doctor                 # post-install self-checks; exit 0 = all green
```

On each device: Amnezia app → import the `vpn://` link → connect. Devices
then reach each other by IP (`100.64.0.x`) or name (`phone.awg`). Open UDP
`--port` in the VPS firewall (443/udp blends into QUIC-like traffic).

## Automation protocol (script against this)

- Every command accepts `--json`: one JSON object on stdout, non-zero exit
  code and `{"ok": false, "error": "..."}` on failure.
- `export AWG_MESH_NONINTERACTIVE=1` disables all prompts.
- `AWG_MESH_ROOT=/path` operates on a different deploy root (default: cwd).
- Exit codes: 0 ok, 1 runtime failure, 2 usage error.
- State lives in `config/` next to the CLI: `server.env` (obfuscation
  params, subnet, image), `peers.db` (JSON peer store), `awg0.conf`,
  `dnsmasq.conf`, `peers.hosts` (MagicDNS records), `start.sh`, `peers/`.

## Operational model (know this before changing anything)

- Two containers: `amnezia-mesh-awg` (the hub, NET_ADMIN, entrypoint
  `start.sh` = awg-quick + iptables) and `amnezia-mesh-dns` (dnsmasq
  sidecar, shares the awg netns). Sidecar must be restarted whenever awg
  is restarted (it does not follow awg into a new netns by itself).
- `peer add` / `peer rename` are restart-free: `awg set` adds the peer to
  the live daemon, SIGHUP makes dnsmasq re-read `peers.hosts`. Existing
  peers keep their sessions.
- `peer revoke` restarts both containers. Removing peers from the
  userspace daemon via UAPI (syncconf/setconf) can silently wedge fresh
  handshakes — a production incident — so only a process restart is
  trusted there.
- Obfuscation params (Jc/Jmin/Jmax/S1/S2/H1-H4) are per-deployment
  random, set at `init`, and must match on server AND every client.
  Regenerating them invalidates all existing profiles.
- `adopt` migrates a running AmneziaWG server under awg-mesh management
  with IPs/keys unchanged. Old containers are only STOPPED — rollback is
  `docker stop amnezia-mesh-awg amnezia-mesh-dns && docker start <old>`.
  Run `awg-mesh adopt --inspect ...` first (read-only preview).
- `awg-mesh monitoring install` adds cron stats
  (`/var/log/amnezia-mesh-stats.log`) and a watchdog.

## Troubleshooting decision tree

1. **Client never handshakes.** On the VPS: does UDP reach the daemon?
   Check the published port vs `AWG_MESH_PORT` in `config/server.env`,
   cloud-provider firewall, and `docker port amnezia-mesh-awg`. Then
   `docker exec amnezia-mesh-awg awg show` — a peer with
   `latest handshake: none` means the client never arrived: wrong
   host/port, UDP blocked, or the profile's obfuscation params differ
   from `config/server.env` (profiles are per-deployment; a re-issued or
   stale profile is the usual cause after a re-init).
2. **Handshake was, traffic dies / certain sites hang.** MTU. Default is
   1280 and start.sh clamps MSS; try a lower MTU in the client profile if
   the uplink is lossy.
3. **Connected, no internet (exit profile).** Exit routes ALL traffic via
   the VPS: needs `net.ipv4.ip_forward=1` (start.sh sets it), NAT
   (start.sh iptables MASQUERADE) and the VPS egress not blocking
   forwarding. `awg-mesh doctor` checks these.
4. **Connected, names don't resolve (`phone.awg`).** DNS sidecar:
   `docker logs amnezia-mesh-dns`. Records come from `config/peers.hosts`
   via `--addn-hosts`, re-read on SIGHUP — if records look right in the
   file but not in answers, SIGHUP didn't fire (only add/rename send it;
   after a manual edit restart the sidecar). Plain `.conf` clients need a
   DNS server set to the hub IP (`100.64.0.1`) for MagicDNS.
5. **Peer was added but can't connect; `awg show` doesn't list it.** The
   live daemon and `config/awg0.conf` diverged (e.g. containers restarted
   manually with a stale config). `docker restart amnezia-mesh-awg
   amnezia-mesh-dns` re-reads everything.
6. **Everything looks wedged after mass changes.** Restart both
   containers; that is always the safe reset.
7. Diagnostics: `awg-mesh doctor --json`, `docker exec amnezia-mesh-awg
   awg show`, `docker logs` both containers,
   `tail /var/log/amnezia-mesh-stats.log` (if monitoring installed).

## Safety rules for agents

- `init` refuses an existing `config/server.env`; `peer` commands refuse
  unknown names. Trust those guards, don't work around them.
- Never run `init`/`peer`/`adopt` against a deploy root the user didn't
  point you at — and never against a production server to "test".
- Revoke is destructive (profiles deleted, devices cut off) and restarts
  the hub for everyone. Confirm with the user first.
- Prefer `doctor --json` before and after any change; it's the project's
  own definition of "healthy".
