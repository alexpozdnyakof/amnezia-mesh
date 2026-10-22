"""amnezia-mesh — self-hosted WireGuard mesh with AmneziaWG obfuscation,
MagicDNS and Tailscale-style exit/mesh profiles."""
import os

__version__ = "0.2.0"


class MeshError(Exception):
    """User-facing error; cli renders it as a json-aware failure message."""


def root() -> str:
    """Repo root: config/, docker-compose.yml, scripts/ live here.
    Overridable via AWG_MESH_ROOT (tests point it at a tmpdir)."""
    return os.environ.get("AWG_MESH_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
