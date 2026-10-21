#!/usr/bin/env python3
"""Amnezia profile codec for amnezia-mesh.

Implements the native Amnezia app profile format (`vpn://` URLs) so generated
profiles import into the official Amnezia app on any platform, plus plain
WireGuard-style `.conf` files for generic awg/wg clients.

vpn:// format (reverse-engineered, verified byte-identical against profiles
produced by the official Amnezia app):
    "vpn://" + base64url( uint32_be(length) + zlib(json, level 9) )
with compact JSON separators (",", ":") and stripped base64 padding.

Commands:
    profile.py gen --env config/server.env --name iphone --ip 100.64.0.3 \
                   --priv <client-priv> --pub <client-pub> --psk <psk> \
                   --out-prefix config/peers/iphone
        Writes <prefix>-exit.vpn, <prefix>-mesh.vpn,
               <prefix>-exit.conf, <prefix>-mesh.conf

    profile.py decode < vpn://... > profile.json
    profile.py roundtrip <file.vpn>
        Decode -> encode -> decode again, assert identical. Self-test.
"""
import argparse
import base64
import ipaddress
import json
import struct
import sys
import zlib

# App-internal identifiers, not our docker names: "amnezia-awg2" is the AWG
# service id inside the Amnezia app. Kept verbatim for import compatibility.
APP_CONTAINER = "amnezia-awg2"
APP_PROTOCOL_VERSION = "3.1"
# Legacy display field the app writes into profiles; client_ip is authoritative.
APP_LEGACY_SUBNET = "10.8.1.0"

OBF_KEYS = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4",
            "H1", "H2", "H3", "H4", "HeaderProtectionKey",
            "ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout",
            "RejectAfterTime", "KeepaliveTimeout", "MaxHandshakeAttempts",
            "RandomTrailers", "DisableCookies"]

I_KEYS = ["I1", "I2", "I3", "I4", "I5"]


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def encode_profile(obj: dict) -> str:
    inner = json.dumps(obj, separators=(",", ":")).encode()
    payload = zlib.compress(inner, 9)
    return "vpn://" + b64url_nopad(struct.pack(">I", len(payload)) + payload)


def decode_profile(url: str) -> dict:
    url = url.strip()
    if url.startswith("vpn://"):
        url = url[len("vpn://"):]
    raw = base64.urlsafe_b64decode(url + "=" * (-len(url) % 4))
    length = struct.unpack(">I", raw[:4])[0]
    return json.loads(zlib.decompress(raw[4:4 + length]))


def render_client_conf(env, peer_ip, allowed, priv, psk, server_pub):
    mtu = env.get("MTU", "1280")
    keepalive = env.get("CLIENT_KEEPALIVE", "15-20")
    lines = [
        "[Interface]",
        f"Address = {peer_ip}/32",
        f"DNS = {env['HUB_IP']}",
        f"MTU = {mtu}",
        f"PrivateKey = {priv}",
    ]
    for k in OBF_KEYS:
        v = env.get(f"OBF_{k.upper()}")
        if v:
            lines.append(f"{k} = {v}")
    lines += [
        "",
        "[Peer]",
        f"PublicKey = {server_pub}",
        f"PresharedKey = {psk}",
        f"AllowedIPs = {allowed}",
        f"Endpoint = {env['AWG_MESH_HOST']}:{env['AWG_MESH_PORT']}",
        f"PersistentKeepalive = {keepalive}",
    ]
    return "\n".join(lines) + "\n"


def build_app_profile(env, name, ptype, peer_ip, allowed, priv, pub, psk, server_pub):
    obf = {k: env[f"OBF_{k.upper()}"] for k in OBF_KEYS if env.get(f"OBF_{k.upper()}")}
    conf = render_client_conf(env, peer_ip, allowed, priv, psk, server_pub)
    last_config = dict(obf)
    last_config.update({k: "" for k in I_KEYS})
    last_config.update({
        "allowed_ips": [allowed],
        "clientId": pub,
        "client_ip": peer_ip,
        "client_priv_key": priv,
        "client_pub_key": pub,
        "config": conf,
        "hostName": env["AWG_MESH_HOST"],
        "mtu": env.get("MTU", "1280"),
        "persistent_keep_alive": env.get("CLIENT_KEEPALIVE", "15-20"),
        "port": int(env["AWG_MESH_PORT"]),
        "psk_key": psk,
        "server_pub_key": server_pub,
    })
    awg_block = dict(obf)
    awg_block.update({k: "" for k in I_KEYS})
    awg_block.update({
        "last_config": json.dumps(last_config),
        "port": env["AWG_MESH_PORT"],
        "protocol_version": APP_PROTOCOL_VERSION,
        "subnet_address": APP_LEGACY_SUBNET,
        "transport_proto": "udp",
    })
    return {
        "containers": [{"awg": awg_block, "container": APP_CONTAINER}],
        "defaultContainer": APP_CONTAINER,
        "description": f"{env['AWG_MESH_HOST']} ({name} {ptype})",
        "dns1": env["HUB_IP"],
        "dns2": "",
        "hostName": env["AWG_MESH_HOST"],
    }


def cmd_gen(args):
    env = load_env(args.env)
    env["HUB_IP"] = str(ipaddress.ip_network(env["AWG_MESH_SUBNET"]).network_address + 1)
    variants = {
        "exit": "0.0.0.0/0",
        "mesh": env["AWG_MESH_SUBNET"],
    }
    written = []
    for ptype, allowed in variants.items():
        prof = build_app_profile(env, args.name, ptype, args.ip, allowed,
                                 args.priv, args.pub, args.psk, env["SERVER_PUB"])
        vpn = encode_profile(prof)
        for suffix, content in ((f"{ptype}.vpn", vpn),
                                (f"{ptype}.conf", prof["containers"][0]["awg"]["last_config"]
                                 and json.loads(prof["containers"][0]["awg"]["last_config"])["config"])):
            path = f"{args.out_prefix}-{suffix}"
            with open(path, "w") as f:
                f.write(content)
            written.append(path)
    for w in written:
        print(w)


def cmd_decode(args):
    obj = decode_profile(args.url if args.url else sys.stdin.read())
    json.dump(obj, sys.stdout, indent=2, ensure_ascii=False)
    print()


def cmd_roundtrip(args):
    with open(args.file) as f:
        url = f.read().strip()
    first = decode_profile(url)
    re_encoded = encode_profile(first)
    again = decode_profile(re_encoded)
    if first != again:
        print("ROUNDTRIP FAILED: re-encoded profile differs", file=sys.stderr)
        sys.exit(1)
    if re_encoded != url:
        # Not an error: deflate streams legitimately vary between zlib builds,
        # and different producers (app versions, OSes) emit different bytes for
        # the same JSON. The Amnezia app decodes semantically.
        print(f"roundtrip OK (semantic; bytes differ by deflate variant): {args.file}")
        return
    print(f"roundtrip OK (byte-identical): {args.file}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="generate .vpn + .conf profiles for a peer")
    g.add_argument("--env", required=True)
    g.add_argument("--name", required=True)
    g.add_argument("--ip", required=True)
    g.add_argument("--priv", required=True)
    g.add_argument("--pub", required=True)
    g.add_argument("--psk", required=True)
    g.add_argument("--out-prefix", required=True)
    g.set_defaults(fn=cmd_gen)

    d = sub.add_parser("decode", help="decode vpn:// URL to JSON")
    d.add_argument("url", nargs="?")
    d.set_defaults(fn=cmd_decode)

    r = sub.add_parser("roundtrip", help="self-test: decode->encode->decode")
    r.add_argument("file")
    r.set_defaults(fn=cmd_roundtrip)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
