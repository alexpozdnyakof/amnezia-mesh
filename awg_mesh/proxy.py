"""Remote mode (stage 7): thin SSH proxy.

`awg-mesh --server <ssh-alias> <args>` (or AWG_MESH_SSH) does not re-implement
any logic locally — it runs `ssh <alias> 'cd <root> && awg-mesh <args>'` with
the system ssh client (keys/aliases from the user's ~/.ssh/config) and passes
stdout/stderr/exit code through. After a MUTATING command (init, adopt without
--inspect, peer add|rename|revoke) exits 0, config/peers/ is pulled back with
scp so the .vpn profiles land in the local root. `skill` and `--version` stay
local. Byte-parity with the Go port is the contract: same remote command
string, same quoting (shlex), same warnings.
"""
import os
import shlex
import shutil
import subprocess
import sys

from . import MeshError, root

_PEER_MUTATIONS = ("add", "rename", "revoke")


def resolve(argv, env):
    """Split --server out of argv. Returns (alias, argv); alias may be None.

    Last --server wins; without the flag AWG_MESH_SSH is the fallback.
    """
    alias = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--server":
            if i + 1 >= len(argv):
                raise MeshError("--server requires a value")
            alias = argv[i + 1]
            i += 2
            continue
        if a.startswith("--server="):
            alias = a[len("--server="):]
            if not alias:
                raise MeshError("--server requires a value")
            i += 1
            continue
        rest.append(a)
        i += 1
    if not alias:
        alias = env.get("AWG_MESH_SSH") or None
    return alias, rest


def local_only(argv):
    """Commands that never go through the proxy."""
    return bool(argv) and argv[0] in ("skill", "--version")


def mutating(argv):
    """Whether a successful run changes remote config/peers/."""
    if not argv:
        return False
    if argv[0] == "init":
        return True
    if argv[0] == "adopt":
        return "--inspect" not in argv[1:]
    return argv[0] == "peer" and len(argv) > 1 and argv[1] in _PEER_MUTATIONS


def _cd_target(remote_root):
    # A quoted '~' would not expand on the remote side — pass it bare.
    return "~" if remote_root == "~" else shlex.quote(remote_root)


def remote_command(argv, env, json_mode):
    """The exact command string the ssh client receives."""
    remote_root = env.get("AWG_MESH_REMOTE_ROOT") or "~"
    parts = ["cd", _cd_target(remote_root), "&&"]
    if env.get("AWG_MESH_NONINTERACTIVE") == "1":
        parts.append("AWG_MESH_NONINTERACTIVE=1")
    parts.append("awg-mesh")
    if json_mode:
        parts.append("--json")
    parts += [shlex.quote(a) for a in argv]
    return " ".join(parts)


def run(alias, argv, json_mode, env=None, local_root=None):
    """Execute argv on the remote host; return the remote exit code."""
    env = os.environ if env is None else env
    cmd = remote_command(argv, env, json_mode)
    try:
        rc = subprocess.run(["ssh", alias, cmd]).returncode
    except OSError:
        raise MeshError("cannot run ssh: no system ssh client in $PATH")
    if rc == 0 and mutating(argv):
        sync_peers(alias, env, local_root if local_root is not None else root())
    return rc


def sync_peers(alias, env, local_root):
    """Mirror <remote root>/config/peers into the local root after a mutation."""
    remote_root = env.get("AWG_MESH_REMOTE_ROOT") or "~"
    cfg = os.path.join(local_root, "config")
    os.makedirs(cfg, exist_ok=True)
    peers = os.path.join(cfg, "peers")
    shutil.rmtree(peers, ignore_errors=True)
    if os.path.isfile(peers):
        os.unlink(peers)
    spec = f"{alias}:{remote_root}/config/peers"
    try:
        rc = subprocess.run(["scp", "-r", "-q", spec, cfg]).returncode
    except OSError:
        rc = 1
    if rc != 0:
        print(f"amnezia-mesh: warning: peer profiles not synced from "
              f"'{alias}' (scp failed)", file=sys.stderr)
