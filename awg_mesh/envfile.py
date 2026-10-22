"""Safe parser for config/server.env.

Values are read as DATA, never sourced or executed — the old bash CLI did
`. server.env`, which executed arbitrary code if the file was tampered with.
"""
from . import MeshError


def load(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        raise MeshError(f"not initialized: {path} missing (run: awg-mesh init)")
    return env


def get(env, key, default=""):
    """Last non-empty value wins, like the old `grep ^KEY= | tail -1`."""
    val = env.get(key)
    return val if val not in (None, "") else default
