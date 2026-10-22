"""peers.db — TSV state: name, ip, pub, psk, created.

Writes go through locked(), which holds an exclusive fcntl lock for the whole
read-modify-write window, so two concurrent `peer add` runs serialize instead
of interleaving torn lines into the db.
"""
import contextlib
import fcntl
import ipaddress
import os
import re

VALID_NAME = re.compile(r"[a-z0-9-]{1,32}\Z")
FIELDS = ("name", "ip", "pub", "psk", "created")


def valid_name(name):
    return bool(name) and VALID_NAME.fullmatch(name) is not None


def parse(text):
    peers = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            name, ip, pub, psk, created = parts[:5]
            if not valid_name(name):
                raise ValueError(f"invalid peer name in db: {name!r}")
            peers.append(dict(zip(FIELDS, (name, ip, pub, psk, created))))
    return peers


def format_line(peer):
    return "\t".join(peer[k] for k in FIELDS) + "\n"


class Tx:
    """Mutable peer list; written back on exit only when dirty."""

    def __init__(self, peer_list):
        self.peers = peer_list
        self.dirty = False

    def add(self, peer):
        self.peers.append(peer)
        self.dirty = True

    def remove(self, name):
        before = len(self.peers)
        self.peers = [p for p in self.peers if p["name"] != name]
        self.dirty = self.dirty or len(self.peers) != before
        return len(self.peers) != before

    def find(self, name):
        for p in self.peers:
            if p["name"] == name:
                return p
        return None


@contextlib.contextmanager
def locked(path):
    """Exclusive-locking read-modify-write transaction over peers.db."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        tx = Tx(parse(f.read()))
        yield tx
        if tx.dirty:
            f.seek(0)
            f.truncate()
            for p in tx.peers:
                f.write(format_line(p))
            f.flush()
            os.fsync(f.fileno())
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read())
    except FileNotFoundError:
        return []


def next_free_ip(subnet, peer_list):
    """First free host IP of the subnet; hub (.1) is reserved."""
    net = ipaddress.ip_network(subnet)
    used = {ipaddress.ip_address(p["ip"]) for p in peer_list}
    for ip in list(net.hosts())[1:]:
        if ip not in used:
            return str(ip)
    return None
