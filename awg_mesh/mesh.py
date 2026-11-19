"""Explicit device-to-device links (Epic 4, stage T1).

Three json files under config/, each with exactly one owner:
  mesh-links.json      operator (CLI)   topology: explicit unordered pairs
  mesh-static.json     operator (CLI)   stable endpoints, hand-marked
  mesh-endpoints.json  collector        observed endpoints (read-only here)

No private keys live in any of them. Writes are atomic (tmp + rename).
Stale observed endpoints never reach a rendered profile: a dead /32 is more
specific than the hub's /24 and would silently blackhole traffic.
"""
import datetime
import json
import os
import re

from . import MeshError

LINKS = "mesh-links.json"
STATIC = "mesh-static.json"
OBSERVED = "mesh-endpoints.json"

# An observed endpoint is usable only while the hub saw a recent handshake
# from it and the collector snapshot itself is fresh.
OBSERVED_MAX_HANDSHAKE_AGE = 300
OBSERVED_MAX_FILE_AGE = 600

_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\Z")


def _path(r, fname):
    return os.path.join(r, "config", fname)


def _read(r, fname, empty):
    try:
        with open(_path(r, fname), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty
    except ValueError as e:
        raise MeshError(f"config/{fname} is not valid json: {e}")
    if not isinstance(data, dict) or data.get("version") != 1:
        raise MeshError(f"config/{fname}: unsupported format (want version 1)")
    return data


def _write(r, fname, data):
    path = _path(r, fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def pair(a, b):
    return frozenset((a, b))


# --- links ---------------------------------------------------------------------

def load_links(r):
    return _read(r, LINKS, {"version": 1, "links": []})["links"]


def save_links(r, links):
    _write(r, LINKS, {"version": 1, "links": links})


def add_link(r, a, b, names, now):
    """Record link a<->b. `names` = known peer names."""
    if a == b:
        raise MeshError("cannot link a device to itself")
    for n in (a, b):
        if n not in names:
            raise MeshError(f"no such peer: {n}")
    links = load_links(r)
    if any(pair(l["a"], l["b"]) == pair(a, b) for l in links):
        raise MeshError(f"already linked: {a} <-> {b}")
    links.append({"a": a, "b": b, "created": now})
    save_links(r, links)


def remove_link(r, a, b):
    links = load_links(r)
    kept = [l for l in links if pair(l["a"], l["b"]) != pair(a, b)]
    if len(kept) == len(links):
        raise MeshError(f"not linked: {a} <-> {b}")
    save_links(r, kept)


def partners(r, name):
    """Names linked to `name`, in link-creation order."""
    out = []
    for l in load_links(r):
        if l["a"] == name:
            out.append(l["b"])
        elif l["b"] == name:
            out.append(l["a"])
    return out


# --- static endpoints ------------------------------------------------------------

def parse_endpoint(text):
    """Validate host:port (IPv4 or hostname). Returns the normalized string."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise MeshError(f"invalid endpoint: {text!r} (want host:port)")
    if not 1 <= int(port) <= 65535:
        raise MeshError(f"invalid endpoint port: {port}")
    if not _HOST.fullmatch(host):
        raise MeshError(f"invalid endpoint host: {host!r}")
    return f"{host}:{int(port)}"


def load_static(r):
    return _read(r, STATIC, {"version": 1, "endpoints": {}})["endpoints"]


def save_static(r, endpoints):
    _write(r, STATIC, {"version": 1, "endpoints": endpoints})


def set_static(r, name, endpoint, note, names):
    if name not in names:
        raise MeshError(f"no such peer: {name}")
    eps = load_static(r)
    eps[name] = {"endpoint": parse_endpoint(endpoint), "note": note or ""}
    save_static(r, eps)


def unset_static(r, name):
    eps = load_static(r)
    if name not in eps:
        raise MeshError(f"no static endpoint for: {name}")
    del eps[name]
    save_static(r, eps)


# --- observed endpoints ----------------------------------------------------------

def _parse_ts(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def load_observed(r, now):
    """{name: endpoint} for usable observed entries; {} when the snapshot is
    missing or older than OBSERVED_MAX_FILE_AGE."""
    data = _read(r, OBSERVED, {"version": 1, "peers": []})
    try:
        age = (_parse_ts(now) - _parse_ts(data["updated"])).total_seconds()
    except (KeyError, ValueError):
        return {}
    if age > OBSERVED_MAX_FILE_AGE:
        return {}
    usable = {}
    for p in data.get("peers", []):
        hs = p.get("handshake_age")
        if p.get("endpoint") and hs is not None and hs <= OBSERVED_MAX_HANDSHAKE_AGE:
            usable[p["name"]] = p["endpoint"]
    return usable


def resolve_endpoint(name, static, observed):
    """(endpoint, source) — static wins over observed; (None, None) if neither."""
    if name in static:
        return static[name]["endpoint"], "static"
    if name in observed:
        return observed[name], "observed"
    return None, None


# --- lifecycle hooks -------------------------------------------------------------

def prune_peer(r, name):
    """peer revoke: drop the peer's links and static endpoint.
    Returns the former partners (they must re-import / re-render)."""
    former = partners(r, name)
    if former:
        save_links(r, [l for l in load_links(r) if name not in (l["a"], l["b"])])
    eps = load_static(r)
    if name in eps:
        del eps[name]
        save_static(r, eps)
    return former


def rename_peers(r, mapping):
    """peer rename (old->new, swaps allowed): rewrite links and static keys."""
    links = load_links(r)
    for l in links:
        l["a"] = mapping.get(l["a"], l["a"])
        l["b"] = mapping.get(l["b"], l["b"])
    if links:
        save_links(r, links)
    eps = load_static(r)
    if any(k in mapping for k in eps):
        save_static(r, {mapping.get(k, k): v for k, v in eps.items()})


# --- profile identity ------------------------------------------------------------

def read_identity(conf_path):
    """(PrivateKey, hub PresharedKey) from an existing client .conf.

    peers.db holds no device private keys, so a p2p profile reuses the
    identity of the device's already-issued -mesh.conf. Adopted devices have
    none: they need `peer rotate` first."""
    try:
        with open(conf_path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        raise MeshError(f"{conf_path} not found: no identity to build a p2p "
                        "profile from (adopted device? run `peer rotate`)")
    priv = psk = None
    for line in text.splitlines():
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key == "PrivateKey":
            priv = val
        elif key == "PresharedKey":
            psk = val
    if not priv or not psk:
        raise MeshError(f"{conf_path}: missing PrivateKey/PresharedKey")
    return priv, psk


# --- direct-peer selection -------------------------------------------------------

def direct_peers(r, name, peer_list, now):
    """Partners of `name` as render inputs.

    Returns (managed, static, skipped): managed = partners with any live
    endpoint, static = the subset with a hand-marked one (app profile),
    skipped = partners with no endpoint at all (left out, never guessed)."""
    by_name = {p["name"]: p for p in peer_list}
    static_eps = load_static(r)
    observed = load_observed(r, now)
    managed, static, skipped = [], [], []
    for partner in partners(r, name):
        p = by_name.get(partner)
        if p is None:
            continue
        ep, src = resolve_endpoint(partner, static_eps, observed)
        if ep is None:
            skipped.append(partner)
            continue
        entry = {"name": partner, "pub": p["pub"], "ip": p["ip"],
                 "endpoint": ep, "source": src}
        managed.append(entry)
        if src == "static":
            static.append(entry)
    return managed, static, skipped
