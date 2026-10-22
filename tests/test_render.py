import os
import shutil

from awg_mesh import render

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
GOLDEN = os.path.join(FIXTURES, "golden")


def _setup(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copy(os.path.join(FIXTURES, "server.env"), cfg / "server.env")
    shutil.copy(os.path.join(FIXTURES, "peers.db"), cfg / "peers.db")
    monkeypatch.setattr(render, "ROOT", str(tmp_path))
    monkeypatch.setattr(render, "ENV_FILE", str(cfg / "server.env"))
    monkeypatch.setattr(render, "PEERS_DB", str(cfg / "peers.db"))
    return cfg


def test_render_matches_legacy_render_py_byte_for_byte(tmp_path, monkeypatch):
    """Golden files were produced by the pre-consolidation lib/render.py
    (commit e8dc344) on the committed synthetic fixture. The new code must
    reproduce them exactly."""
    cfg = _setup(tmp_path, monkeypatch)
    render.render_all()
    for name in ("awg0.conf", "dnsmasq.conf", "start.sh"):
        produced = (cfg / name).read_bytes()
        expected = open(os.path.join(GOLDEN, name), "rb").read()
        assert produced == expected, f"{name} diverged from legacy render.py"


def test_awg0_conf_written_with_0600(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch)
    render.render_all()
    assert (cfg / "awg0.conf").stat().st_mode & 0o777 == 0o600


def test_start_sh_is_executable(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch)
    render.render_all()
    assert os.access(cfg / "start.sh", os.X_OK)
