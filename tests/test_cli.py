import json
import os
import shutil
import types

import pytest

from awg_mesh import cli, peers, render


@pytest.fixture(autouse=True)
def _reset_json_mode(monkeypatch):
    monkeypatch.setattr(cli, "JSON_MODE", False)


stdin_log = []  # (compose args, stdin) for calls that fed stdin


@pytest.fixture
def mesh(tmp_path, monkeypatch):
    """Initialized throwaway root: server.env + peers.db, faked
    compose (records calls, rc=0) and deterministic keygen."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "peers").mkdir()  # init/adopt create it; profile renders land here
    here = os.path.dirname(os.path.abspath(__file__))
    shutil.copy(os.path.join(here, "fixtures", "server.env"), cfg / "server.env")
    shutil.copy(os.path.join(here, "fixtures", "peers.db"), cfg / "peers.db")
    calls = []
    stdin_log.clear()

    def fake_compose(r, env, *args, input_text=None):
        calls.append(list(args))
        if input_text is not None:
            stdin_log.append((list(args), input_text))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.compose_mod, "compose", fake_compose)
    monkeypatch.setattr(cli.keygen, "gen_keypair",
                        lambda image: ("NEWPRIV", "NEWPUB"))
    monkeypatch.setattr(cli.keygen, "gen_psk", lambda image: "NEWPSK")
    monkeypatch.setenv("AWG_MESH_ROOT", str(tmp_path))
    monkeypatch.setenv("AWG_MESH_NONINTERACTIVE", "1")
    # render resolves its inputs from module-level constants
    monkeypatch.setattr(render, "ROOT", str(tmp_path))
    monkeypatch.setattr(render, "ENV_FILE", str(cfg / "server.env"))
    monkeypatch.setattr(render, "PEERS_DB", str(cfg / "peers.db"))
    return tmp_path, calls


def run(argv):
    try:
        return cli.main(argv)
    except SystemExit as e:
        return e.code


def db_names(root):
    return [p["name"] for p in peers.load(str(root / "config" / "peers.db"))]


def last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# --- peer rename --------------------------------------------------------------

def test_rename_single_pair_shape_unchanged(mesh, capsys):
    root, calls = mesh
    assert run(["--json", "peer", "rename", "laptop-test", "laptop"]) == 0
    assert last_json(capsys) == {"ok": True, "renamed": "laptop-test",
                                 "name": "laptop"}
    assert db_names(root) == ["hub-test", "laptop", "phone-test"]
    # one SIGHUP for the whole operation
    sighups = [c for c in calls if c[:3] == ["exec", "-T", "dns"]]
    assert len(sighups) == 1


def test_rename_bulk_pairs_and_swap(mesh, capsys):
    root, calls = mesh
    assert run(["--json", "peer", "rename",
                "hub-test", "phone-test",   # freed name
                "phone-test", "hub-test",   # swap
                "laptop-test", "laptop"]) == 0
    assert db_names(root) == ["phone-test", "laptop", "hub-test"]
    assert last_json(capsys) == {"ok": True, "renamed": {
        "hub-test": "phone-test", "phone-test": "hub-test",
        "laptop-test": "laptop"}}
    assert len([c for c in calls if c[:3] == ["exec", "-T", "dns"]]) == 1


@pytest.mark.parametrize("argv,msg", [
    (["peer", "rename", "laptop-test"], "takes <old> <new> pairs"),
    (["peer", "rename", "laptop-test", "x", "ghost", "y"], "no such peer: ghost"),
    (["peer", "rename", "laptop-test", "Bad_Name"], "invalid peer name: Bad_Name"),
    (["peer", "rename", "laptop-test", "hub-test"], "peer already exists: hub-test"),
    (["peer", "rename", "laptop-test", "new", "phone-test", "new"],
     "duplicate new name: new"),
    (["peer", "rename", "laptop-test", "a", "laptop-test", "b"],
     "peer renamed twice in one call: laptop-test"),
])
def test_rename_bulk_validation_leaves_db_untouched(mesh, capsys, argv, msg):
    root, _ = mesh
    before = db_names(root)
    assert run(argv) == 1
    assert msg in capsys.readouterr().err
    assert db_names(root) == before


# --- peer rotate --------------------------------------------------------------

def test_rotate_reissues_keys(mesh, capsys):
    root, calls = mesh
    assert run(["--json", "peer", "rotate", "laptop-test"]) == 0
    plist = peers.load(str(root / "config" / "peers.db"))
    rotated = [p for p in plist if p["name"] == "laptop-test"][0]
    assert rotated["pub"] == "NEWPUB"
    assert rotated["psk"] == "NEWPSK"
    assert rotated["ip"] == "100.64.0.3"  # IP survives rotation
    # old pubkey must leave the daemon -> restart path, like revoke
    restarts = [c for c in calls if c and c[0] == "restart"]
    assert restarts == [["restart", "awg"], ["restart", "dns"]]
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["rotated"] == "laptop-test"
    assert out["ip"] == "100.64.0.3"
    profiles = root / "config" / "peers"
    assert (profiles / "laptop-test-exit.conf").exists()
    # the .conf carries the device's new private key; the peer-side public
    # key lands in the vpn:// app profile, not here
    assert "PrivateKey = NEWPRIV" in (profiles / "laptop-test-exit.conf").read_text()


def test_rotate_aborts_on_decline(mesh, monkeypatch, capsys):
    root, _ = mesh
    monkeypatch.delenv("AWG_MESH_NONINTERACTIVE")
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert run(["peer", "rotate", "laptop-test"]) == 1
    assert "aborted" in capsys.readouterr().err
    assert [p["pub"] for p in peers.load(str(root / "config" / "peers.db"))
            if p["name"] == "laptop-test"][0] != "NEWPUB"


def test_rotate_unknown_peer(mesh, capsys):
    assert run(["peer", "rotate", "ghost"]) == 1
    assert "no such peer: ghost" in capsys.readouterr().err


# --- custom dns records ---------------------------------------------------------

def test_dns_add_list_remove(mesh, capsys):
    root, calls = mesh
    assert run(["--json", "dns", "add", "nas", "100.64.0.50"]) == 0
    assert last_json(capsys) == {"ok": True, "name": "nas.awg",
                                 "ip": "100.64.0.50"}
    text = (root / "config" / "custom.hosts").read_text()
    assert "100.64.0.50\tnas.awg" in text
    assert len([c for c in calls if c[:3] == ["exec", "-T", "dns"]]) == 1

    assert run(["--json", "dns", "list"]) == 0
    assert last_json(capsys) == {"ok": True, "records": [
        {"name": "nas.awg", "ip": "100.64.0.50"}]}

    # remove by short name; SIGHUP fires again
    assert run(["--json", "dns", "remove", "nas"]) == 0
    assert last_json(capsys) == {"ok": True, "removed": "nas.awg"}
    assert "nas.awg" not in (root / "config" / "custom.hosts").read_text()
    assert len([c for c in calls if c[:3] == ["exec", "-T", "dns"]]) == 2


def test_dns_list_empty(mesh, capsys):
    root, _ = mesh
    assert run(["dns", "list"]) == 0
    captured = capsys.readouterr()
    assert "no custom records" in captured.out
    assert run(["--json", "dns", "list"]) == 0
    assert last_json(capsys) == {"ok": True, "records": []}


@pytest.mark.parametrize("argv,msg", [
    (["dns", "add", "nas.awg", "100.64.0.50"], "invalid record name: nas.awg"),
    (["dns", "add", "NAS", "100.64.0.50"], "invalid record name: NAS"),
    (["dns", "add", "nas", "not-an-ip"], "invalid IP: not-an-ip"),
    (["dns", "add", "nas", "fd00::1"], "invalid IP: fd00::1 (IPv4 only)"),
    (["dns", "add", "laptop-test", "100.64.0.50"],
     "'laptop-test' is already served by MagicDNS"),
    (["dns", "add", "hub", "100.64.0.50"], "'hub' is already served"),
    (["dns", "remove", "ghost"], "no such record: ghost.awg"),
])
def test_dns_validation(mesh, capsys, argv, msg):
    assert run(argv) == 1
    assert msg in capsys.readouterr().err


def test_dns_add_duplicate(mesh, capsys):
    assert run(["dns", "add", "nas", "100.64.0.50"]) == 0
    assert run(["dns", "add", "nas", "100.64.0.51"]) == 1
    assert "record already exists: nas.awg" in capsys.readouterr().err


# --- mesh link / endpoint / config ---------------------------------------------

def _issue(root, name):
    """Issue the regular profiles for a fixture peer (source of identity)."""
    from awg_mesh import profile
    p = next(x for x in peers.load(str(root / "config" / "peers.db"))
             if x["name"] == name)
    profile.generate_profiles(
        env_file=str(root / "config" / "server.env"), name=name, ip=p["ip"],
        priv=f"{name}-PRIV", pub=p["pub"], psk=p["psk"],
        out_prefix=str(root / "config" / "peers" / name))


def _p2p(root, name, ext="conf"):
    return root / "config" / "peers" / f"{name}-mesh-p2p.{ext}"


def test_mesh_link_endpoint_config_flow(mesh, capsys):
    root, _ = mesh
    for n in ("laptop-test", "hub-test"):
        _issue(root, n)
    assert run(["--json", "mesh", "link", "add", "laptop-test", "hub-test"]) == 0
    assert last_json(capsys)["linked"] == ["laptop-test", "hub-test"]
    # no endpoint for the partner yet: profile is hub-only, nothing guessed
    assert _p2p(root, "laptop-test").read_text().count("[Peer]") == 1

    assert run(["--json", "mesh", "endpoint", "set", "hub-test",
                "203.0.113.50:51820", "--note", "port-forward"]) == 0
    assert last_json(capsys)["affected"] == ["laptop-test"]
    conf = _p2p(root, "laptop-test").read_text()
    assert conf.count("[Peer]") == 2
    assert "AllowedIPs = 100.64.0.2/32" in conf
    assert "Endpoint = 203.0.113.50:51820" in conf
    assert "laptop-test-PRIV" in conf            # identity reused, not new keys
    assert "hub-test-PRIV" not in conf

    from awg_mesh import profile
    prof = profile.decode_profile(_p2p(root, "laptop-test", "vpn").read_text())
    last = json.loads(prof["containers"][0]["awg"]["last_config"])
    assert "203.0.113.50:51820" in last["config"]

    assert run(["--json", "mesh", "status"]) == 0
    row = last_json(capsys)["links"][0]
    assert row["direct_capable"] is False and row["missing"] == ["laptop-test"]


def test_mesh_config_without_links_fails(mesh, capsys):
    assert run(["--json", "mesh", "config", "laptop-test"]) == 1
    assert "no links" in last_json(capsys)["error"]


def test_mesh_link_without_identity_warns_not_fails(mesh, capsys):
    root, _ = mesh                      # no profiles issued (adopted-like)
    assert run(["mesh", "link", "add", "laptop-test", "hub-test"]) == 0
    assert not _p2p(root, "laptop-test").exists()
    assert "peer rotate" in capsys.readouterr().err


def test_mesh_link_remove_deletes_p2p_files(mesh, capsys):
    root, _ = mesh
    for n in ("laptop-test", "hub-test"):
        _issue(root, n)
    run(["mesh", "link", "add", "laptop-test", "hub-test"])
    assert _p2p(root, "laptop-test").exists()
    run(["mesh", "link", "remove", "laptop-test", "hub-test"])
    assert not _p2p(root, "laptop-test").exists()


def test_revoke_prunes_links_and_refreshes_partners(mesh, capsys):
    root, _ = mesh
    for n in ("laptop-test", "hub-test"):
        _issue(root, n)
    run(["mesh", "endpoint", "set", "hub-test", "203.0.113.50:51820"])
    run(["mesh", "link", "add", "laptop-test", "hub-test"])
    assert run(["--json", "peer", "revoke", "hub-test"]) == 0
    assert json.load(open(root / "config" / "mesh-links.json"))["links"] == []
    assert json.load(open(root / "config" / "mesh-static.json"))["endpoints"] == {}
    assert not _p2p(root, "laptop-test").exists()


def test_rename_rewrites_links(mesh, capsys):
    root, _ = mesh
    run(["mesh", "link", "add", "laptop-test", "hub-test"])
    assert run(["peer", "rename", "hub-test", "nas"]) == 0
    links = json.load(open(root / "config" / "mesh-links.json"))["links"]
    assert {links[0]["a"], links[0]["b"]} == {"laptop-test", "nas"}


def test_peer_add_applies_psk_live(mesh, capsys):
    """Regression: restart-free add used to omit the PSK, so the new peer
    could not handshake until the hub restarted."""
    root, calls = mesh
    assert run(["peer", "add", "fresh"]) == 0
    args, stdin = next((a, i) for a, i in stdin_log if "preshared-key" in a)
    assert args[args.index("preshared-key") + 1] == "/dev/stdin"
    assert "allowed-ips" in args and "NEWPSK" not in args  # never in argv
    assert stdin == "NEWPSK\n"
