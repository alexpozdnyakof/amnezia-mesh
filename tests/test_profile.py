import json
import os

from awg_mesh import profile

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ENV_FILE = os.path.join(FIXTURES, "server.env")

PRIV = "A" * 44   # shape-only stand-ins; nothing here touches real keys
PUB = "B" * 44
PSK = "C" * 44


def _gen(tmp_path):
    prefix = str(tmp_path / "peer")
    written = profile.generate_profiles(
        env_file=ENV_FILE, name="laptop", ip="100.64.0.7",
        priv=PRIV, pub=PUB, psk=PSK, out_prefix=prefix)
    return written, prefix


def test_gen_writes_four_profiles(tmp_path):
    written, prefix = _gen(tmp_path)
    assert sorted(written) == sorted([
        f"{prefix}-exit.vpn", f"{prefix}-mesh.vpn",
        f"{prefix}-exit.conf", f"{prefix}-mesh.conf"])
    for path in written:
        assert os.path.getsize(path) > 0


def test_vpn_profile_structure_and_routing(tmp_path):
    _, prefix = _gen(tmp_path)
    with open(f"{prefix}-exit.vpn") as f:
        exit_prof = profile.decode_profile(f.read())
    with open(f"{prefix}-mesh.vpn") as f:
        mesh_prof = profile.decode_profile(f.read())

    for prof in (exit_prof, mesh_prof):
        awg = prof["containers"][0]
        assert awg["container"] == "amnezia-awg2"
        assert awg["awg"]["protocol_version"] == "3.1"
        assert awg["awg"]["transport_proto"] == "udp"
        assert prof["hostName"] == "192.0.2.10"
        assert prof["dns1"] == "100.64.0.1"      # hub answers MagicDNS
        assert "laptop" in prof["description"]

    exit_last = json.loads(exit_prof["containers"][0]["awg"]["last_config"])
    mesh_last = json.loads(mesh_prof["containers"][0]["awg"]["last_config"])
    assert exit_last["allowed_ips"] == ["0.0.0.0/0"]
    assert mesh_last["allowed_ips"] == ["100.64.0.0/24"]
    assert exit_last["client_ip"] == "100.64.0.7"
    assert "Endpoint = 192.0.2.10:443" in exit_last["config"]


def test_roundtrip_is_semantically_stable(tmp_path):
    _, prefix = _gen(tmp_path)
    for ptype in ("exit", "mesh"):
        url = open(f"{prefix}-{ptype}.vpn").read()
        decoded = profile.decode_profile(url)
        redecoded = profile.decode_profile(profile.encode_profile(decoded))
        assert redecoded == decoded


def test_conf_variant_matches_embedded_config(tmp_path):
    _, prefix = _gen(tmp_path)
    for ptype in ("exit", "mesh"):
        prof = profile.decode_profile(open(f"{prefix}-{ptype}.vpn").read())
        embedded = json.loads(prof["containers"][0]["awg"]["last_config"])["config"]
        assert open(f"{prefix}-{ptype}.conf").read() == embedded
