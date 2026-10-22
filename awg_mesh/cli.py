"""amnezia-mesh CLI.

Same surface as the original bash CLI: init / peer add|list|revoke / doctor /
monitoring, a global --json accepted anywhere on the command line, env
overrides AWG_MESH_*, and non-interactive mode via AWG_MESH_NONINTERACTIVE=1.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys

from . import MeshError, __version__, root
from . import compose as compose_mod
from . import doctor as doctor_mod
from . import keygen, peers, profile, render
from .envfile import load as load_env

JSON_MODE = False


def say(msg):
    """Progress note, human mode only (stdout stays machine-readable)."""
    if not JSON_MODE:
        print(msg, file=sys.stderr)


def out(msg=""):
    if not JSON_MODE:
        print(msg)


def fail(msg):
    if JSON_MODE:
        print(json.dumps({"ok": False, "error": str(msg)}))
    else:
        print(f"amnezia-mesh: error: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(**fields):
    if JSON_MODE:
        print(json.dumps({"ok": True, **fields}))


def confirm(question):
    if os.environ.get("AWG_MESH_NONINTERACTIVE") == "1":
        return True
    print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        ans = input()
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def strip_interface_block(text):
    """Remove the [Interface] section from an awg-quick config. syncconf only
    understands [Peer] sections ([Interface] keys like Address are wg-quick-
    isms and rejected), so we strip the block before piping the config in."""
    lines, skipping = [], False
    for line in text.splitlines():
        if line.strip() == "[Interface]":
            skipping = True
            continue
        if skipping and line.startswith("["):
            skipping = False
        if not skipping:
            lines.append(line)
    return "\n".join(lines)


def apply_conf(env):
    """Push awg0.conf into the running container and reload dns."""
    r = root()
    with open(os.path.join(r, "config", "awg0.conf")) as f:
        peers_only = strip_interface_block(f.read())
    sync = compose_mod.compose(r, env, "exec", "-T", "awg", "awg", "syncconf",
                               "awg0", "/dev/stdin", input_text=peers_only + "\n")
    if sync.returncode == 0:
        say("applied via awg syncconf")
    else:
        say(f"syncconf failed ({sync.stderr.strip()})")
    # Production lesson: the userspace daemon can silently wedge fresh
    # handshakes after peers are stripped/re-added via syncconf (the iphone
    # incident). Restart unconditionally — syncconf alone gives false success.
    compose_mod.compose(r, env, "restart", "awg")
    # dnsmasq ignores SIGHUP for config changes — restart the sidecar too.
    compose_mod.compose(r, env, "restart", "dns")


def cmd_init(args):
    r = root()
    env_file = os.path.join(r, "config", "server.env")
    if os.path.exists(env_file):
        fail(f"already initialized: {env_file} exists (delete config/ to start over)")
    host = args.host
    if not host:
        if os.environ.get("AWG_MESH_NONINTERACTIVE") == "1":
            fail("--host is required in non-interactive mode")
        print("Public host or IP of this server: ", end="", file=sys.stderr, flush=True)
        host = sys.stdin.readline().strip()
    if not host:
        fail("host is required")

    say(f"pulling image {args.image} ...")
    pull = subprocess.run(["docker", "pull", args.image],
                          capture_output=True, text=True)
    if pull.returncode != 0:
        fail(f"docker pull failed: {args.image}: {pull.stderr.strip()}")

    say("probing image for I1-I5 (CPS) support ...")
    i_sup = keygen.probe_i_support(args.image)
    if i_sup == "NO_AWGQUICK":
        fail(f"image {args.image} has no awg-quick; "
             "use the standard amneziavpn/amneziawg-go image")

    say("generating server keys and obfuscation profile ...")
    server_priv, server_pub = keygen.gen_keypair(args.image)

    os.makedirs(os.path.join(r, "config", "peers"), exist_ok=True)
    open(os.path.join(r, "config", "peers.db"), "a").close()
    lines = [
        "# amnezia-mesh server state. Local secrets — never commit.",
        f"AWG_MESH_HOST={host}",
        f"AWG_MESH_PORT={args.port}",
        f"AWG_MESH_SUBNET={args.subnet}",
        f"AWG_MESH_DOMAIN={args.domain}",
        "AWG_MESH_DNS1=1.1.1.1",
        "AWG_MESH_DNS2=1.0.0.1",
        f"AWG_MESH_IMAGE={args.image}",
        f"AWG_MESH_RDP_REJECT={1 if args.rdp_reject else 0}",
        f"AWG_MESH_I_SUPPORTED={1 if i_sup == 'SUPPORTED' else 0}",
        "LISTEN_PORT=41480",
        "MTU=1280",
        "SERVER_KEEPALIVE=25",
        "CLIENT_KEEPALIVE=15-20",
        f"SERVER_PRIV={server_priv}",
        f"SERVER_PUB={server_pub}",
    ]
    lines += keygen.gen_obfuscation()
    with open(env_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(env_file, 0o600)

    render.render_all()

    say("starting containers ...")
    up = compose_mod.compose(r, load_env(env_file), "up", "-d")
    if up.returncode != 0:
        fail(f"docker compose up failed: {up.stderr.strip()}")

    results = doctor_mod.run_checks(r)
    if any(not c["ok"] for c in results):
        fail("post-start checks failed (see: awg-mesh doctor)")

    out()
    out("amnezia-mesh is up.")
    out("Next: awg-mesh peer add <device-name>   "
        "# then import the printed vpn:// link in the Amnezia app")
    ok(host=host, port=int(args.port), subnet=args.subnet,
       i_supported=(i_sup == "SUPPORTED"))


def cmd_peer_add(args):
    r = root()
    env_file = os.path.join(r, "config", "server.env")
    if not os.path.exists(env_file):
        fail("not initialized (run: awg-mesh init)")
    name = args.name
    if not peers.valid_name(name):
        fail(f"invalid peer name: {name} (lowercase letters, digits, dash, max 32)")
    if args.type not in ("exit", "mesh", "both"):
        fail("--type must be exit|mesh|both")
    env = load_env(env_file)

    # The lock is held for the whole check-generate-append window: two
    # concurrent `peer add` runs serialize instead of racing on the same IP.
    with peers.locked(os.path.join(r, "config", "peers.db")) as tx:
        if tx.find(name):
            fail(f"peer already exists: {name}")
        ip = peers.next_free_ip(env["AWG_MESH_SUBNET"], tx.peers)
        if not ip:
            fail(f"subnet {env['AWG_MESH_SUBNET']} exhausted")
        say(f"generating keys for {name} ...")
        priv, pub = keygen.gen_keypair(env["AWG_MESH_IMAGE"])
        psk = keygen.gen_psk(env["AWG_MESH_IMAGE"])
        created = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        tx.add({"name": name, "ip": ip, "pub": pub, "psk": psk,
                "created": created})

    render.render_all()
    apply_conf(env)

    prefix = os.path.join(r, "config", "peers", name)
    profile.generate_profiles(env_file=env_file, name=name, ip=ip,
                              priv=priv, pub=pub, psk=psk, out_prefix=prefix)

    out()
    out(f"peer '{name}' added: {ip} "
        f"(profiles: {prefix}-exit.vpn / {prefix}-mesh.vpn)")
    out("import the .vpn link in the Amnezia app, "
        "or use the .conf with any awg/wg client")
    ok(name=name, ip=ip,
       profiles=[f"{prefix}-exit.vpn", f"{prefix}-mesh.vpn"])


def cmd_peer_list(args):
    r = root()
    env_file = os.path.join(r, "config", "server.env")
    if not os.path.exists(env_file):
        fail("not initialized (run: awg-mesh init)")
    plist = peers.load(os.path.join(r, "config", "peers.db"))
    if not JSON_MODE:
        if not plist:
            out("no peers")
        else:
            for p in plist:
                out(f"{p['name']:<20} {p['ip']:<15} {p['created']}")
    ok(peers=[{"name": p["name"], "ip": p["ip"], "created": p["created"]}
              for p in plist])


def cmd_peer_revoke(args):
    r = root()
    env_file = os.path.join(r, "config", "server.env")
    if not os.path.exists(env_file):
        fail("not initialized (run: awg-mesh init)")
    name = args.name
    env = load_env(env_file)
    with peers.locked(os.path.join(r, "config", "peers.db")) as tx:
        if not tx.find(name):
            fail(f"no such peer: {name}")
        if not confirm(f"revoke peer '{name}'? its devices will lose access"):
            fail("aborted")
        tx.remove(name)
    render.render_all()
    apply_conf(env)
    for path in (glob.glob(os.path.join(r, "config", "peers", f"{name}-*.vpn"))
                 + glob.glob(os.path.join(r, "config", "peers", f"{name}-*.conf"))):
        os.unlink(path)
    say(f"peer '{name}' revoked")
    ok(revoked=name)


def cmd_doctor(args):
    results = doctor_mod.run_checks(root())
    if JSON_MODE:
        print(json.dumps({"ok": all(c["ok"] for c in results), "checks": results}))
    else:
        for c in results:
            mark = "ok  " if c["ok"] else "FAIL"
            print(f"{mark}  {c['name']:<18} {c['detail']}")
    return 0 if all(c["ok"] for c in results) else 1


def cmd_monitoring(args):
    r = root()
    scripts = os.path.join(r, "scripts")
    if args.action == "install":
        steps = [
            ["sudo", "cp",
             os.path.join(scripts, "awg-stats.sh"),
             os.path.join(scripts, "awg-watchdog.sh"),
             "/usr/local/sbin/"],
            ["sudo", "cp",
             os.path.join(scripts, "amnezia-mesh.cron"),
             "/etc/cron.d/amnezia-mesh"],
        ]
        for step in steps:
            cp = subprocess.run(step, capture_output=True, text=True)
            if cp.returncode != 0:
                fail(f"install failed (sudo?): {cp.stderr.strip()}")
        say("monitoring installed: /usr/local/sbin/awg-{stats,watchdog}.sh "
            "+ /etc/cron.d/amnezia-mesh")
        ok(installed=True)
    else:
        rm = subprocess.run(
            ["sudo", "rm", "-f",
             "/usr/local/sbin/awg-stats.sh", "/usr/local/sbin/awg-watchdog.sh",
             "/etc/cron.d/amnezia-mesh"],
            capture_output=True, text=True)
        if rm.returncode != 0:
            fail(f"uninstall failed (sudo?): {rm.stderr.strip()}")
        say("monitoring removed")
        ok(installed=False)


def build_parser():
    p = argparse.ArgumentParser(
        prog="awg-mesh",
        description="Self-hosted WireGuard mesh with AmneziaWG obfuscation, "
                    "MagicDNS and Tailscale-style exit/mesh profiles.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="generate keys + obfuscation, render "
                                    "configs, start containers")
    i.add_argument("--host")
    i.add_argument("--port", default="443")
    i.add_argument("--subnet", default="100.64.0.0/24")
    i.add_argument("--image", default="amneziavpn/amneziawg-go:latest")
    i.add_argument("--domain", default="awg")
    i.add_argument("--rdp-reject", action="store_true")
    i.set_defaults(fn=cmd_init)

    pr = sub.add_parser("peer", help="manage devices")
    pr_sub = pr.add_subparsers(dest="peer_cmd", required=True)
    pa = pr_sub.add_parser("add", help="new device: keys, IP, profiles")
    pa.add_argument("name")
    pa.add_argument("--type", default="both",
                    help="exit | mesh | both (informational: both profile "
                         "files are always generated)")
    pa.set_defaults(fn=cmd_peer_add)
    pl = pr_sub.add_parser("list", help="devices, IPs, creation dates")
    pl.set_defaults(fn=cmd_peer_list)
    pv = pr_sub.add_parser("revoke", help="remove device (config applied, "
                                          "profiles deleted)")
    pv.add_argument("name")
    pv.set_defaults(fn=cmd_peer_revoke)

    d = sub.add_parser("doctor", help="post-install self-checks")
    d.set_defaults(fn=cmd_doctor)

    m = sub.add_parser("monitoring", help="cron stats + watchdog")
    m.add_argument("action", choices=["install", "uninstall"])
    m.set_defaults(fn=cmd_monitoring)
    return p


def main(argv=None):
    global JSON_MODE
    argv = list(sys.argv[1:] if argv is None else argv)
    # The bash CLI accepted --json anywhere on the command line; keep that.
    if "--json" in argv:
        JSON_MODE = True
        argv.remove("--json")
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except MeshError as e:
        fail(e)
    except ValueError as e:
        fail(e)
    except KeyboardInterrupt:
        fail("interrupted")
