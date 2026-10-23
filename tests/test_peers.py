import threading

import pytest

from awg_mesh import peers


def _peer(name, ip):
    return {"name": name, "ip": ip, "pub": "p", "psk": "k", "created": "t"}


def test_valid_name_dns_label():
    assert peers.valid_name("macbook-3")
    assert peers.valid_name("a" * 32)
    assert not peers.valid_name("Hub")          # uppercase
    assert not peers.valid_name("")
    assert not peers.valid_name("x" * 33)
    assert not peers.valid_name("bad_name")     # underscore
    assert not peers.valid_name("ünïcode")


def test_next_free_ip_reserves_hub_and_skips_used():
    assert peers.next_free_ip("100.64.0.0/24", []) == "100.64.0.2"  # .1 is hub
    used = [_peer("a", "100.64.0.2"), _peer("b", "100.64.0.3")]
    assert peers.next_free_ip("100.64.0.0/24", used) == "100.64.0.4"


def test_next_free_ip_exhaustion():
    all_ips = [str(ip) for ip in list(__import__("ipaddress").ip_network(
        "100.64.0.0/30").hosts())[1:]]  # only .1 (hub) and .2
    used = [_peer("a", "100.64.0.2")]
    assert peers.next_free_ip("100.64.0.0/30", used) is None


def test_add_remove_roundtrip(tmp_path):
    db = str(tmp_path / "peers.db")
    with peers.locked(db) as tx:
        tx.add(_peer("a", "100.64.0.2"))
    loaded = peers.load(db)
    assert [p["name"] for p in loaded] == ["a"]
    with peers.locked(db) as tx:
        assert tx.find("a") is not None
        assert tx.remove("a") is True
        assert tx.remove("a") is False  # already gone, not dirty
    assert peers.load(db) == []


def test_db_is_created_on_first_write(tmp_path):
    db = str(tmp_path / "sub" / "peers.db")
    with peers.locked(db) as tx:
        tx.add(_peer("a", "100.64.0.2"))
    assert len(peers.load(db)) == 1


def test_rename_peer(tmp_path):
    db = str(tmp_path / "peers.db")
    with peers.locked(db) as tx:
        tx.add(_peer("a", "100.64.0.2"))
        tx.add(_peer("b", "100.64.0.3"))
    with peers.locked(db) as tx:
        assert tx.rename("a", "phone") is True
        assert tx.rename("a", "x") is False      # old name gone
        assert tx.rename("phone", "b") is False  # target taken
        assert tx.rename("nope", "x") is False   # missing
    loaded = peers.load(db)
    assert [p["name"] for p in loaded] == ["phone", "b"]
    assert loaded[0]["ip"] == "100.64.0.2"  # keys/IPs untouched


def test_parse_rejects_invalid_name():
    with pytest.raises(ValueError):
        peers.parse("Bad\t100.64.0.2\tp\tk\tt\n")


def test_concurrent_adds_serialize_without_torn_lines(tmp_path):
    db = str(tmp_path / "peers.db")
    errors = []

    def worker(i):
        try:
            with peers.locked(db) as tx:
                ip = peers.next_free_ip("100.64.0.0/24", tx.peers)
                tx.add(_peer(f"w{i}", ip))
        except Exception as e:  # noqa: BLE001 - surfaced via assert below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    plist = peers.load(db)
    assert len(plist) == 8
    assert len({p["ip"] for p in plist}) == 8  # flock + in-lock allocation: no dupes
    with open(db) as f:
        lines = f.readlines()
    assert len(lines) == 8
    assert all(line.count("\t") == 4 and line.endswith("\n") for line in lines)


# --- cmd-level: peer list --json carries pub (TUI maps awg show pubkeys) ----


def test_cmd_peer_list_json_includes_pub(tmp_path, monkeypatch, capsys):
    from awg_mesh import cli

    monkeypatch.setattr(cli, "root", lambda: str(tmp_path))
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "server.env").write_text("AWG_MESH_HOST=h\n")
    with peers.locked(str(cfg / "peers.db")) as tx:
        tx.add({"name": "phone", "ip": "100.64.0.3", "pub": "P" * 44,
                "psk": "K" * 44, "created": "2026-10-20T12:00:00Z"})
    assert cli.main(["--json", "peer", "list"]) == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["peers"] == [{"name": "phone", "ip": "100.64.0.3",
                             "pub": "P" * 44,
                             "created": "2026-10-20T12:00:00Z"}]
