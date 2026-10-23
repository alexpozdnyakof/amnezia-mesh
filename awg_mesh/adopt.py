"""Parser for adopting an existing AmneziaWG/WireGuard server config.

Reads an awg0.conf (from a file or from inside a running container) and
converts it into amnezia-mesh state (server.env + peers.db). Everything
cryptographic is carried over verbatim — server key, obfuscation profile,
peer keys and PSKs — so existing client profiles keep working unchanged.
"""
import ipaddress
import re

from . import MeshError
from .peers import valid_name
from .render import OBF_KEYS

# awg0.conf key -> server.env key for [Interface] lines we understand.
INTERFACE_MAP = {
    "PrivateKey": "SERVER_PRIV",
    "Address": "_ADDRESS",       # validated separately, becomes AWG_MESH_SUBNET
    "ListenPort": "LISTEN_PORT",
    "MTU": "MTU",
}
OBF_MAP = {k: "OBF_" + k.upper() for k in OBF_KEYS}

# Peer comment produced by render.py: "# name (added 2026-10-20T12:00:00Z)"
ADDED_RE = re.compile(r"^(?P<name>.+?)\s*\(added\s+(?P<created>[^)]+)\)\s*$")
GENERATED_NAME_LEN = 6


class ParsedConf:
    def __init__(self):
        self.env = {}            # SERVER_PRIV, LISTEN_PORT, MTU, OBF_*
        self.subnet = None       # CIDR string, hub == network+1 (asserted)
        self.peers = []          # {name, ip, pub, psk, created}
        self.keepalive = None    # first peer's PersistentKeepalive
        self.warnings = []


def _split_comment(text):
    """'# name (added ...)' -> (name, created) or (text, None)."""
    m = ADDED_RE.match(text)
    if m:
        return m.group("name").strip(), m.group("created").strip()
    return text.strip(), None


def _sanitize_name(name):
    """Comment names must become valid DNS-label peer names."""
    cleaned = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return cleaned or None


def parse(text):
    """Parse awg0.conf content -> ParsedConf. Raises MeshError on anything
    we cannot represent faithfully (unknown [Interface] keys, bad Address,
    missing peer keys) — adopt never drops config silently."""
    parsed = ParsedConf()
    section = None
    current = None
    pending_comment = None
    unknown = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if section == "Peer" and current is not None and current["pub"] is None:
                pending_comment = line.lstrip("# ").strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            section = name
            if name == "Peer":
                current = {"name": None, "ip": None, "pub": None,
                           "psk": None, "created": None}
                parsed.peers.append(current)
                pending_comment = None
            continue
        if "=" not in line:
            parsed.warnings.append(f"skipped unrecognized line: {line!r}")
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()

        if section == "Interface":
            if key in INTERFACE_MAP:
                parsed.env[INTERFACE_MAP[key]] = value
            elif key in OBF_MAP:
                parsed.env[OBF_MAP[key]] = value
            else:
                unknown.append(key)
        elif section == "Peer":
            if pending_comment and current["name"] is None:
                current["name"], current["created"] = _split_comment(pending_comment)
                pending_comment = None
            if key == "PublicKey":
                current["pub"] = value
            elif key == "PresharedKey":
                current["psk"] = value
            elif key == "AllowedIPs":
                first = value.split(",")[0].strip()
                current["ip"] = first.split("/")[0]
            elif key == "PersistentKeepalive":
                if parsed.keepalive is None:
                    parsed.keepalive = value
            # other peer keys (e.g. Endpoint) are client-side concerns; ignored

    if unknown:
        raise MeshError(
            "unsupported [Interface] keys: " + ", ".join(sorted(set(unknown)))
            + " — extend adopt.INTERFACE_MAP or open an issue; "
              "refusing to adopt rather than drop them silently")
    _validate(parsed)
    _finalize_names(parsed)
    return parsed


def _validate(parsed):
    if not parsed.env.get("SERVER_PRIV"):
        raise MeshError("no PrivateKey found in [Interface]")
    addr = parsed.env.pop("_ADDRESS", None)
    if not addr:
        raise MeshError("no Address found in [Interface]")
    try:
        iface = ipaddress.ip_interface(addr)
        net = ipaddress.ip_network(addr, strict=False)
    except ValueError as e:
        raise MeshError(f"invalid Address in [Interface]: {addr!r} ({e})")
    if iface.ip != net.network_address + 1:
        raise MeshError(
            f"server Address {iface.ip} is not the first host of {net} "
            f"(expected {net.network_address + 1}) — non-standard layout, "
            "refusing to guess")
    parsed.subnet = str(net)

    for peer in parsed.peers:
        label = peer["name"] or peer["pub"] or "?"
        if not peer["pub"]:
            raise MeshError(f"peer {label}: missing PublicKey")
        if not peer["psk"]:
            raise MeshError(f"peer {label}: missing PresharedKey "
                            "(mesh profiles require PSKs)")
        if not peer["ip"]:
            raise MeshError(f"peer {label}: missing AllowedIPs")
        try:
            ipaddress.ip_address(peer["ip"])
        except ValueError:
            raise MeshError(f"peer {label}: invalid IP {peer['ip']!r}")


def _finalize_names(parsed):
    """Fill missing names (peer-xxxx from pubkey), sanitize, dedupe."""
    seen = set()
    for peer in parsed.peers:
        name = _sanitize_name(peer["name"]) if peer["name"] else None
        if name is None:
            name = "peer-" + peer["pub"][:GENERATED_NAME_LEN]
            parsed.warnings.append(
                f"peer {peer['pub'][:8]}… has no name comment; "
                f"generated '{name}'")
        elif peer["name"] != name:
            parsed.warnings.append(
                f"peer name {peer['name']!r} sanitized to '{name}'")
        base, counter = name, 2
        while name in seen:
            name = f"{base}-{counter}"
            counter += 1
        seen.add(name)
        peer["name"] = name


def build_state(parsed, *, host, port, domain, image, dns1, dns2,
                rdp_reject, server_pub, now):
    """(env_pairs, peer_records) ready to be written to config/."""
    env_pairs = [
        ("AWG_MESH_HOST", host),
        ("AWG_MESH_PORT", str(port)),
        ("AWG_MESH_SUBNET", parsed.subnet),
        ("AWG_MESH_DOMAIN", domain),
        ("AWG_MESH_DNS1", dns1),
    ]
    if dns2:
        env_pairs.append(("AWG_MESH_DNS2", dns2))
    env_pairs += [
        ("AWG_MESH_IMAGE", image),
        ("AWG_MESH_RDP_REJECT", "1" if rdp_reject else "0"),
        ("AWG_MESH_I_SUPPORTED", "0"),
        ("LISTEN_PORT", parsed.env.get("LISTEN_PORT", "41480")),
        ("MTU", parsed.env.get("MTU", "1280")),
        ("SERVER_KEEPALIVE", parsed.keepalive or "25"),
        ("CLIENT_KEEPALIVE", "15-20"),
        ("SERVER_PRIV", parsed.env["SERVER_PRIV"]),
        ("SERVER_PUB", server_pub),
    ]
    env_pairs += sorted((k, v) for k, v in parsed.env.items()
                        if k.startswith("OBF_"))

    peer_records = [{
        "name": p["name"],
        "ip": p["ip"],
        "pub": p["pub"],
        "psk": p["psk"],
        "created": p["created"] or now,
    } for p in parsed.peers]
    return env_pairs, peer_records
