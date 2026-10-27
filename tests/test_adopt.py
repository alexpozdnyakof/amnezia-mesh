import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from awg_mesh import MeshError, adopt, cli, keygen, peers, render
from awg_mesh import compose as compose_mod
from awg_mesh import doctor as doctor_mod

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
GOLDEN = os.path.join(FIXTURES, "golden")
GOLDEN_CONF = os.path.join(GOLDEN, "awg0.conf")

PRIV = "A" * 44
PUB = "B" * 44
PSK = "C" * 44

BASE_CONF = f"""[Interface]
PrivateKey = {PRIV}
Address = 100.64.0.1/24
ListenPort = 41480
MTU = 1280
Jc = 5

[Peer]
# test-peer (added 2026-10-20T12:00:00Z)
PublicKey = {PUB}
PresharedKey = {PSK}
AllowedIPs = 100.64.0.2/32
PersistentKeepalive = 25
"""


def _write_state(tmp_path, monkeypatch, conf_text=None):
    """adopt-style: parse conf, write env+db into tmp config/, patch render."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    parsed = adopt.parse(conf_text if conf_text is not None
                         else open(GOLDEN_CONF).read())
    env_pairs, records = adopt.build_state(
        parsed, host="192.0.2.10", port="443", domain="awg",
        image="amneziavpn/amneziawg-go:latest", dns1="1.1.1.1",
        dns2="1.0.0.1", rdp_reject=True, server_pub="D" * 44,
        now="2026-10-22T00:00:00Z")
    with open(cfg / "server.env", "w") as f:
        f.write("\n".join(f"{k}={v}" for k, v in env_pairs) + "\n")
    with peers.locked(str(cfg / "peers.db")) as tx:
        for rec in records:
            tx.add(rec)
    monkeypatch.setattr(render, "ROOT", str(tmp_path))
    monkeypatch.setattr(render, "ENV_FILE", str(cfg / "server.env"))
    monkeypatch.setattr(render, "PEERS_DB", str(cfg / "peers.db"))
    return cfg


def test_roundtrip_adopt_render_matches_golden_byte_for_byte(tmp_path,
                                                             monkeypatch):
    """golden/awg0.conf (output of the original render.py) -> adopt parser ->
    server.env + peers.db -> render must reproduce golden exactly."""
    cfg = _write_state(tmp_path, monkeypatch)
    render.render_all()
    for name in ("awg0.conf", "dnsmasq.conf", "peers.hosts", "start.sh"):
        produced = (cfg / name).read_bytes()
        expected = open(os.path.join(GOLDEN, name), "rb").read()
        assert produced == expected, f"{name} diverged after adopt roundtrip"


def test_parse_unknown_interface_key_aborts():
    with pytest.raises(MeshError, match="Foo"):
        adopt.parse(BASE_CONF.replace("Jc = 5", "Jc = 5\nFoo = 1"))


def test_parse_address_not_first_host_aborts():
    with pytest.raises(MeshError, match="first host"):
        adopt.parse(BASE_CONF.replace("Address = 100.64.0.1/24",
                                      "Address = 100.64.0.5/24"))


def test_parse_peer_missing_psk_aborts():
    with pytest.raises(MeshError, match="PresharedKey"):
        adopt.parse(BASE_CONF.replace(f"PresharedKey = {PSK}\n", ""))


def test_peer_without_comment_gets_generated_name():
    conf = BASE_CONF.replace("# test-peer (added 2026-10-20T12:00:00Z)\n", "")
    parsed = adopt.parse(conf)
    assert parsed.peers[0]["name"] == "peer-" + PUB[:6].lower()
    assert any("generated" in w for w in parsed.warnings)


def test_peer_name_collision_gets_suffix():
    peer = f"""[Peer]
# test-peer
PublicKey = {"E" * 44}
PresharedKey = {PSK}
AllowedIPs = 100.64.0.3/32
"""
    parsed = adopt.parse(BASE_CONF + peer)
    names = [p["name"] for p in parsed.peers]
    assert names == ["test-peer", "test-peer-2"]


def test_build_state_created_fallback():
    conf = BASE_CONF.replace(" (added 2026-10-20T12:00:00Z)", "")
    parsed = adopt.parse(conf)
    _, records = adopt.build_state(
        parsed, host="h", port=443, domain="awg", image="img",
        dns1="1.1.1.1", dns2="", rdp_reject=False,
        server_pub="D" * 44, now="2026-10-23T00:00:00Z")
    assert records[0]["created"] == "2026-10-23T00:00:00Z"


# --- real-world shapes found on a hand-maintained production conf -----------

def test_generated_names_from_base64_pubkeys_are_valid():
    """Hand-maintained confs have no name comments; pubkey slices contain
    base64 chars (uppercase, /, +) and must sanitize to valid peer names."""
    conf = BASE_CONF.replace("# test-peer (added 2026-10-20T12:00:00Z)\n", "")
    parsed = adopt.parse(conf)
    for peer in parsed.peers:
        assert peers.valid_name(peer["name"]), peer["name"]


def test_non_added_parenthetical_is_stripped():
    conf = BASE_CONF.replace("# test-peer (added 2026-10-20T12:00:00Z)",
                             "# macbook-2 (key rotated 2026-10-27, "
                             "was 1qtP0Bz2 without PSK)")
    parsed = adopt.parse(conf)
    assert parsed.peers[0]["name"] == "macbook-2"
    assert parsed.peers[0]["created"] is None


def test_overlong_comment_name_is_truncated_to_valid():
    long_note = "some very long hand written comment about this device " * 3
    conf = BASE_CONF.replace("# test-peer (added 2026-10-20T12:00:00Z)",
                             f"# {long_note}")
    parsed = adopt.parse(conf)
    name = parsed.peers[0]["name"]
    assert len(name) <= 32
    assert peers.valid_name(name)


def test_prod_shaped_conf_produces_valid_state(tmp_path, monkeypatch):
    """Peer mix from the real server: unnamed peers with base64 keys, one
    long hand-written note. adopt -> render must succeed end to end."""
    conf = f"""[Interface]
PrivateKey = {PRIV}
Address = 100.64.0.1/24
ListenPort = 41480
MTU = 1280
Jc = 5
Jmin = 14
Jmax = 52
S1 = 37
S2 = 34
S3 = 200
S4 = 128
H1 = 1641846015
H2 = 1919277141
H3 = 1925319215
H4 = 4119105387
HeaderProtectionKey = {PSK}
ContentPaddingAddition = 2-10
RekeyAfterTime = 120-180
RekeyTimeout = 5-10
RejectAfterTime = 540-600
KeepaliveTimeout = 8-12
MaxHandshakeAttempts = 80-100
RandomTrailers = on
DisableCookies = on

[Peer]
PublicKey = {"D38w6bG59pL7AdUC" + "x" * 27}=
PresharedKey = {PSK}
AllowedIPs = 100.64.0.1/32
PersistentKeepalive = 25

[Peer]
PublicKey = {"0idOZrIUtbQTnDIP" + "y" * 27}=
PresharedKey = {PSK}
AllowedIPs = 100.64.0.2/32

[Peer]
PublicKey = {"n117z/3AeWhuaMNN" + "z" * 27}=
PresharedKey = {PSK}
AllowedIPs = 100.64.0.3/32

[Peer]
# macbook-2 (key rotated 2026-10-27, was 1qtP0Bz2 without PSK)
PublicKey = {"2Q41d93FiHUxxiUL" + "w" * 27}=
PresharedKey = {PSK}
AllowedIPs = 100.64.0.4/32

[Peer]
# macbook-3
PublicKey = {"3MiTsQx5h+JxUnmm" + "v" * 27}=
PresharedKey = {PSK}
AllowedIPs = 100.64.0.5/32
"""
    cfg = _write_state(tmp_path, monkeypatch, conf)
    render.render_all()  # must not raise
    assert (cfg / "awg0.conf").exists()
    db_peers = peers.load(str(cfg / "peers.db"))
    assert all(peers.valid_name(p["name"]) for p in db_peers)
    assert {p["ip"] for p in db_peers} == {
        f"100.64.0.{i}" for i in range(1, 6)}


# --- cmd-level tests with docker/compose/doctor mocked -----------------------

def _patch_runtime(monkeypatch, tmp_path, doctor_results=None):
    monkeypatch.setattr(cli, "root", lambda: str(tmp_path))
    cfg = tmp_path / "config"
    monkeypatch.setattr(render, "ROOT", str(tmp_path))
    monkeypatch.setattr(render, "ENV_FILE", str(cfg / "server.env"))
    monkeypatch.setattr(render, "PEERS_DB", str(cfg / "peers.db"))
    monkeypatch.setattr(keygen, "pub_from_priv", lambda image, priv: "D" * 44)
    calls = []
    monkeypatch.setattr(compose_mod, "compose",
                        lambda root, env, *a, **kw: (
                            calls.append(("compose",) + a),
                            SimpleNamespace(returncode=0, stdout="",
                                            stderr=""))[1])
    monkeypatch.setattr(
        doctor_mod, "run_checks",
        lambda root: doctor_results if doctor_results is not None else
        [{"name": "all", "ok": True, "detail": "stub"}])
    return calls


def _patch_docker(monkeypatch, calls, conf_text):
    def fake_run(argv, **kw):
        calls.append(tuple(argv))
        if argv[:2] == ["docker", "exec"]:
            return SimpleNamespace(returncode=0, stdout=conf_text,
                                   stderr="")
        if argv[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0,
                                   stdout="amneziavpn/amneziawg-go:latest\n",
                                   stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)


def test_cmd_adopt_config_source_success(tmp_path, monkeypatch, capsys):
    calls = _patch_runtime(monkeypatch, tmp_path)
    rc = cli.main(["--json", "adopt", "--config", GOLDEN_CONF,
                   "--image", "img:latest", "--host", "192.0.2.10",
                   "--port", "443", "--dns2", "1.0.0.1", "--rdp-reject"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["peers"] == 3
    env_file = tmp_path / "config" / "server.env"
    assert env_file.exists()
    assert env_file.stat().st_mode & 0o777 == 0o600
    # no container source -> no docker stop/start, compose up ran, doctor ran
    kinds = [c[0] for c in calls]
    assert kinds == ["compose"]
    assert calls[0][1] == "up"


def test_cmd_adopt_container_source_order_and_rollback(tmp_path, monkeypatch):
    calls = _patch_runtime(monkeypatch, tmp_path,
                           doctor_results=[{"name": "x", "ok": False,
                                            "detail": "boom"}])
    _patch_docker(monkeypatch, calls, open(GOLDEN_CONF).read())
    with pytest.raises(SystemExit) as exc:
        cli.main(["adopt", "--container", "old-awg", "--host",
                  "192.0.2.10", "--port", "443"])
    assert exc.value.code == 1
    flat = [c for c in calls]
    seq = [c for c in flat if c[0] == "compose" or c[:2] == ("docker", "stop")
           or c[:2] == ("docker", "start")]
    kinds = []
    for c in seq:
        if c[0] == "compose":
            kinds.append(c[1])
        elif c[1] in ("stop", "start"):
            kinds.append(c[1])
    assert kinds == ["stop", "up", "down", "start"]


# --- adopt --inspect: read-only pre-migration preview for the TUI wizard ----


def test_cmd_adopt_inspect_config_source_no_mutation(tmp_path, monkeypatch,
                                                     capsys):
    calls = _patch_runtime(monkeypatch, tmp_path)
    rc = cli.main(["--json", "adopt", "--inspect", "--config", GOLDEN_CONF,
                   "--image", "img:latest"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    insp = out["inspect"]
    assert out["ok"] and insp["image"] == "img:latest"
    assert insp["server_pub"] == "D" * 44  # pub_from_priv stub
    assert insp["subnet"] == "100.64.0.0/24"
    assert len(insp["peers"]) == 3
    assert {"name", "ip", "pub", "created"} <= set(insp["peers"][0])
    assert not (tmp_path / "config" / "server.env").exists()
    assert calls == []  # inspect never touches compose or docker stop/start


def test_cmd_adopt_inspect_container_source_uses_docker(tmp_path,
                                                        monkeypatch, capsys):
    calls = _patch_runtime(monkeypatch, tmp_path)
    _patch_docker(monkeypatch, calls, open(GOLDEN_CONF).read())
    rc = cli.main(["--json", "adopt", "--inspect", "--container", "old-awg"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["inspect"]["source"] == "container 'old-awg'"
    assert len(out["inspect"]["peers"]) == 3
    docker_cmds = [c[1] for c in calls if c[0] == "docker"]
    assert "exec" in docker_cmds and "inspect" in docker_cmds
    assert "stop" not in docker_cmds and "start" not in docker_cmds


def test_cmd_adopt_inspect_bad_conf_fails_with_json_error(tmp_path,
                                                         monkeypatch, capsys):
    _patch_runtime(monkeypatch, tmp_path)
    bad = tmp_path / "bad.conf"
    bad.write_text("[Interface]\nPrivateKey = x\nAddress = 10.0.0.1/24\n"
                   "Foo = 1\n")
    with pytest.raises(SystemExit) as exc:
        cli.main(["--json", "adopt", "--inspect", "--config", str(bad),
                  "--image", "img"])
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert not out["ok"] and "Foo" in out["error"]


def test_cmd_adopt_host_required_unless_inspect(tmp_path, monkeypatch,
                                                capsys):
    _patch_runtime(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--json", "adopt", "--config", GOLDEN_CONF,
                  "--image", "img"])
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert not out["ok"] and "host" in out["error"]
