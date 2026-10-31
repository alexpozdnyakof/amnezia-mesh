import os
import stat

import pytest

from awg_mesh import MeshError, cli, proxy, skill


def _script(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


@pytest.fixture
def fake_transports(tmp_path, monkeypatch):
    """Fake ssh/scp on PATH; ssh prints a marker, scp mirrors a canned dir."""
    log = tmp_path / "calls.log"
    canned = tmp_path / "canned-peers"
    canned.mkdir()
    (canned / "phone-exit.conf").write_text("[Interface]\n# canned\n")
    _script(tmp_path, "ssh", f'printf "%s\\n" "ssh $*" >>"{log}"\n'
                            'echo "FAKE-SSH-OUT"\n'
                            'exit "${FAKE_SSH_RC:-0}"\n')
    _script(tmp_path, "scp", f'printf "%s\\n" "scp $*" >>"{log}"\n'
                             'dest="${!#}"\n'
                             'if [ "${FAKE_SCP_FAIL:-0}" = 1 ]; then exit 1; fi\n'
                             f'mkdir -p "$dest"\n'
                             f'cp -R "{canned}" "$dest/peers"\n')
    monkeypatch.setenv("PATH", f'{tmp_path / "bin"}:{os.environ["PATH"]}')
    monkeypatch.delenv("AWG_MESH_SSH", raising=False)
    monkeypatch.delenv("AWG_MESH_REMOTE_ROOT", raising=False)
    monkeypatch.delenv("AWG_MESH_NONINTERACTIVE", raising=False)
    return log


def _calls(log):
    return log.read_text().splitlines()


# --- resolve -----------------------------------------------------------------

def test_resolve_flag_separate_and_equals():
    alias, argv = proxy.resolve(["--server", "vps", "peer", "list"], {})
    assert alias == "vps"
    assert argv == ["peer", "list"]
    alias, argv = proxy.resolve(["--server=vps", "peer", "list"], {})
    assert alias == "vps"
    assert argv == ["peer", "list"]


def test_resolve_last_flag_wins_and_flag_anywhere():
    alias, argv = proxy.resolve(
        ["peer", "--server", "one", "list", "--server=two"], {})
    assert alias == "two"
    assert argv == ["peer", "list"]


def test_resolve_env_fallback():
    alias, argv = proxy.resolve(["peer", "list"], {"AWG_MESH_SSH": "env-vps"})
    assert alias == "env-vps"
    alias, _ = proxy.resolve(["peer", "list"], {})
    assert alias is None


def test_resolve_missing_value():
    with pytest.raises(MeshError):
        proxy.resolve(["peer", "list", "--server"], {})
    with pytest.raises(MeshError):
        proxy.resolve(["--server="], {})


# --- classification ----------------------------------------------------------

def test_local_only():
    assert proxy.local_only(["skill"])
    assert proxy.local_only(["--version"])
    assert not proxy.local_only(["peer", "list"])
    assert not proxy.local_only([])


def test_mutating():
    assert proxy.mutating(["init"])
    assert proxy.mutating(["adopt", "--config", "/x", "--image", "i"])
    assert not proxy.mutating(["adopt", "--inspect", "--config", "/x"])
    assert proxy.mutating(["peer", "add", "phone"])
    assert proxy.mutating(["peer", "rename", "a", "b"])
    assert proxy.mutating(["peer", "revoke", "a"])
    assert not proxy.mutating(["peer", "list"])
    assert not proxy.mutating(["doctor"])
    assert not proxy.mutating([])


# --- remote command string ---------------------------------------------------

def test_remote_command_defaults():
    cmd = proxy.remote_command(["peer", "list"], {}, False)
    assert cmd == "cd ~ && awg-mesh peer list"


def test_remote_command_env_and_json():
    env = {"AWG_MESH_REMOTE_ROOT": "/opt/mesh", "AWG_MESH_NONINTERACTIVE": "1"}
    cmd = proxy.remote_command(["peer", "add", "phone"], env, True)
    assert cmd == ("cd /opt/mesh && AWG_MESH_NONINTERACTIVE=1 "
                   "awg-mesh --json peer add phone")


def test_remote_command_quotes_args_and_spaced_root():
    cmd = proxy.remote_command(["peer", "add", "weird name!", "it's"], {}, False)
    assert cmd == "cd ~ && awg-mesh peer add 'weird name!' 'it'\"'\"'s'"
    env = {"AWG_MESH_REMOTE_ROOT": "/opt/my mesh"}
    cmd = proxy.remote_command(["doctor"], env, False)
    assert cmd == "cd '/opt/my mesh' && awg-mesh doctor"


# --- end to end over the fake transports --------------------------------------

def test_run_passes_through_exit_code(fake_transports, capfd):
    os.environ["FAKE_SSH_RC"] = "23"
    try:
        rc = proxy.run("vps", ["peer", "list"], json_mode=False,
                       local_root="/tmp/unused-awg-mesh-test")
    finally:
        del os.environ["FAKE_SSH_RC"]
    assert rc == 23
    assert "FAKE-SSH-OUT" in capfd.readouterr().out


def test_run_syncs_peers_after_mutation(fake_transports, tmp_path):
    root = tmp_path / "root"
    (root / "config" / "peers").mkdir(parents=True)
    (root / "config" / "peers" / "stale.conf").write_text("old")
    rc = proxy.run("vps", ["peer", "add", "phone"], json_mode=True,
                   local_root=str(root))
    assert rc == 0
    pulled = root / "config" / "peers" / "phone-exit.conf"
    assert pulled.exists()
    assert not (root / "config" / "peers" / "stale.conf").exists()
    ssh_line, scp_line = _calls(fake_transports)
    assert ssh_line == ("ssh vps cd ~ && awg-mesh --json peer add phone")
    assert scp_line.startswith("scp -r -q vps:~/config/peers ")


def test_run_no_sync_for_read_only_or_failure(fake_transports, tmp_path):
    root = tmp_path / "root"
    rc = proxy.run("vps", ["peer", "list"], json_mode=False, local_root=str(root))
    assert rc == 0
    assert not (root / "config").exists()
    assert len(_calls(fake_transports)) == 1  # ssh only, no scp

    os.environ["FAKE_SSH_RC"] = "1"
    try:
        rc = proxy.run("vps", ["peer", "add", "phone"], json_mode=False,
                       local_root=str(root))
    finally:
        del os.environ["FAKE_SSH_RC"]
    assert rc == 1
    assert len(_calls(fake_transports)) == 2  # still no scp


def test_run_warns_when_scp_fails(fake_transports, tmp_path, capfd):
    os.environ["FAKE_SCP_FAIL"] = "1"
    try:
        rc = proxy.run("vps", ["init"], json_mode=True,
                       local_root=str(tmp_path / "root"))
    finally:
        del os.environ["FAKE_SCP_FAIL"]
    assert rc == 0
    err = capfd.readouterr().err
    assert ("amnezia-mesh: warning: peer profiles not synced from "
            "'vps' (scp failed)") in err


# --- main() integration -------------------------------------------------------

def test_main_proxies_when_env_set(fake_transports, tmp_path, capfd):
    os.environ["AWG_MESH_SSH"] = "env-vps"
    try:
        rc = cli.main(["peer", "list"])
    finally:
        del os.environ["AWG_MESH_SSH"]
    assert rc == 0
    assert "FAKE-SSH-OUT" in capfd.readouterr().out


def test_main_skill_stays_local_even_with_server(fake_transports, capsys):
    rc = cli.main(["--server", "vps", "skill"])
    assert rc == 0
    assert capsys.readouterr().out == skill.load()
