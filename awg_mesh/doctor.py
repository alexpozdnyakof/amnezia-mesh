"""Post-install self-checks.

Each check returns (ok, detail); results are aggregated and serialized with a
single json.dumps — the old bash CLI concatenated JSON by hand and broke on
quotes in docker output. Check names, order and retry behaviour match the
bash implementation.
"""
import ipaddress
import os
import re
import subprocess
import time

from . import compose as compose_mod
from .envfile import load

RETRIES = 15
RETRY_DELAY = 1.0


def run_checks(root):
    """Returns a list of {"name", "ok", "detail"} dicts in a fixed order."""
    checks = []
    env_file = os.path.join(root, "config", "server.env")

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    daemon = subprocess.run(["docker", "info"], capture_output=True, text=True)
    add("docker-daemon", daemon.returncode == 0, "docker daemon reachable")

    initialized = os.path.isfile(env_file)
    add("initialized", initialized, env_file)
    if not initialized:
        return checks

    env = load(env_file)

    def comp(*args, input_text=None):
        return compose_mod.compose(root, env, *args, input_text=input_text)

    ps = comp("ps", "--format", "{{.Name}} {{.Status}}")
    add("awg-container",
        ps.returncode == 0 and re.search(r"amnezia-mesh-awg.*Up", ps.stdout),
        comp("ps", "--format", "{{.Status}}", "awg").stdout.splitlines()[0]
        if ps.returncode == 0 and ps.stdout else "")

    ps_dns = comp("ps", "--format", "{{.Name}} {{.Status}}")
    add("dns-container",
        ps_dns.returncode == 0 and re.search(r"amnezia-mesh-dns.*Up", ps_dns.stdout),
        comp("ps", "--format", "{{.Status}}", "dns").stdout.splitlines()[0]
        if ps_dns.returncode == 0 and ps_dns.stdout else "")

    # The userspace daemon needs a moment after container start. Note:
    # `awg show <iface> listen-port` misbehaves in amneziawg-tools (kernel
    # netlink fallback) — parse the full `awg show` output instead.
    listen = ""
    for _ in range(RETRIES):
        show = comp("exec", "-T", "awg", "awg", "show")
        m = re.search(r"listening port:\s*(\d+)", show.stdout)
        if show.returncode == 0 and m:
            listen = m.group(1)
            break
        time.sleep(RETRY_DELAY)
    add("listen-port", bool(listen), f"awg0 listens on {listen}")

    fwd = comp("exec", "-T", "awg", "cat", "/proc/sys/net/ipv4/ip_forward")
    add("ip-forward", fwd.returncode == 0 and "1" in fwd.stdout,
        "net.ipv4.ip_forward inside awg netns")

    domain = env.get("AWG_MESH_DOMAIN", "awg")
    hub = str(ipaddress.ip_network(env["AWG_MESH_SUBNET"]).network_address + 1)
    # dnsmasq sidecar needs a moment (apk add + bind on awg0).
    dns_ok = False
    for _ in range(RETRIES):
        ns = comp("exec", "-T", "dns", "nslookup", f"hub.{domain}", hub)
        if ns.returncode == 0 and hub in ns.stdout:
            dns_ok = True
            break
        time.sleep(RETRY_DELAY)
    add("magicdns", dns_ok, f"hub.{domain} resolves to {hub} via dnsmasq")

    port = env["AWG_MESH_PORT"]
    dp = subprocess.run(["docker", "port", "amnezia-mesh-awg"],
                        capture_output=True, text=True)
    add("port-published", dp.returncode == 0 and f":{port}" in dp.stdout,
        f"udp {port} -> 41480")

    return checks
