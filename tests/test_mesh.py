import json

import pytest

from awg_mesh import MeshError, mesh, profile

NOW = "2026-11-19T12:00:00Z"
NAMES = {"laptop", "nas", "phone"}


@pytest.fixture
def r(tmp_path):
    (tmp_path / "config").mkdir()
    return str(tmp_path)


def write_observed(r, updated, peers):
    with open(f"{r}/config/mesh-endpoints.json", "w") as f:
        json.dump({"version": 1, "updated": updated, "peers": peers}, f)


# --- links ---------------------------------------------------------------------

def test_link_add_is_unordered_and_unique(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    with pytest.raises(MeshError, match="already linked"):
        mesh.add_link(r, "nas", "laptop", NAMES, NOW)
    assert mesh.partners(r, "nas") == ["laptop"]
    assert mesh.partners(r, "laptop") == ["nas"]


def test_link_add_validates(r):
    with pytest.raises(MeshError, match="itself"):
        mesh.add_link(r, "nas", "nas", NAMES, NOW)
    with pytest.raises(MeshError, match="no such peer: ghost"):
        mesh.add_link(r, "nas", "ghost", NAMES, NOW)


def test_link_remove(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    mesh.remove_link(r, "nas", "laptop")
    assert mesh.load_links(r) == []
    with pytest.raises(MeshError, match="not linked"):
        mesh.remove_link(r, "nas", "laptop")


def test_links_file_atomic_and_versioned(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    data = json.load(open(f"{r}/config/mesh-links.json"))
    assert data["version"] == 1
    assert data["links"] == [{"a": "laptop", "b": "nas", "created": NOW}]
    import os
    assert not os.path.exists(f"{r}/config/mesh-links.json.tmp")


def test_unsupported_version_rejected(r):
    open(f"{r}/config/mesh-links.json", "w").write('{"version": 2}')
    with pytest.raises(MeshError, match="unsupported"):
        mesh.load_links(r)


# --- endpoints -----------------------------------------------------------------

@pytest.mark.parametrize("text,norm", [
    ("203.0.113.50:51820", "203.0.113.50:51820"),
    ("nas.example.org:0443", "nas.example.org:443"),
])
def test_parse_endpoint_ok(text, norm):
    assert mesh.parse_endpoint(text) == norm


@pytest.mark.parametrize("text", [
    "203.0.113.50", ":51820", "host:", "host:0", "host:70000", "ho st:1",
    "-bad:1", "host:12a",
])
def test_parse_endpoint_rejects(text):
    with pytest.raises(MeshError):
        mesh.parse_endpoint(text)


def test_static_set_unset(r):
    mesh.set_static(r, "nas", "203.0.113.50:51820", "port-forward", NAMES)
    assert mesh.load_static(r)["nas"] == {"endpoint": "203.0.113.50:51820",
                                          "note": "port-forward"}
    with pytest.raises(MeshError, match="no such peer"):
        mesh.set_static(r, "ghost", "1.2.3.4:5", "", NAMES)
    mesh.unset_static(r, "nas")
    with pytest.raises(MeshError, match="no static endpoint"):
        mesh.unset_static(r, "nas")


def test_observed_requires_fresh_snapshot_and_handshake(r):
    write_observed(r, "2026-11-19T11:59:00Z", [
        {"name": "laptop", "endpoint": "1.1.1.1:1", "handshake_age": 30},
        {"name": "nas", "endpoint": "2.2.2.2:2", "handshake_age": 9999},
        {"name": "phone", "endpoint": "", "handshake_age": 5},
        {"name": "old", "endpoint": "3.3.3.3:3", "handshake_age": None},
    ])
    assert mesh.load_observed(r, NOW) == {"laptop": "1.1.1.1:1"}


def test_observed_stale_snapshot_is_ignored(r):
    write_observed(r, "2026-11-19T11:00:00Z", [
        {"name": "laptop", "endpoint": "1.1.1.1:1", "handshake_age": 1}])
    assert mesh.load_observed(r, NOW) == {}


def test_observed_missing_file(r):
    assert mesh.load_observed(r, NOW) == {}


def test_static_beats_observed():
    st = {"nas": {"endpoint": "9.9.9.9:9"}}
    ob = {"nas": "1.1.1.1:1", "laptop": "2.2.2.2:2"}
    assert mesh.resolve_endpoint("nas", st, ob) == ("9.9.9.9:9", "static")
    assert mesh.resolve_endpoint("laptop", st, ob) == ("2.2.2.2:2", "observed")
    assert mesh.resolve_endpoint("phone", st, ob) == (None, None)


# --- lifecycle -----------------------------------------------------------------

def test_prune_peer_drops_links_and_static(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    mesh.add_link(r, "nas", "phone", NAMES, NOW)
    mesh.set_static(r, "nas", "1.2.3.4:5", "", NAMES)
    assert mesh.prune_peer(r, "nas") == ["laptop", "phone"]
    assert mesh.load_links(r) == []
    assert mesh.load_static(r) == {}


def test_rename_peers_supports_swap(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    mesh.set_static(r, "nas", "1.2.3.4:5", "", NAMES)
    mesh.rename_peers(r, {"laptop": "nas", "nas": "laptop"})
    assert mesh.partners(r, "nas") == ["laptop"]
    assert list(mesh.load_static(r)) == ["laptop"]


# --- identity + direct peer selection --------------------------------------------

def test_read_identity(tmp_path):
    p = tmp_path / "x-mesh.conf"
    p.write_text("[Interface]\nPrivateKey = PRIV\n\n[Peer]\nPresharedKey = PSK\n")
    assert mesh.read_identity(str(p)) == ("PRIV", "PSK")


def test_read_identity_missing_hints_rotate(tmp_path):
    with pytest.raises(MeshError, match="peer rotate"):
        mesh.read_identity(str(tmp_path / "nope.conf"))


PEERS = [
    {"name": "laptop", "ip": "100.64.0.3", "pub": "LAPPUB"},
    {"name": "nas", "ip": "100.64.0.5", "pub": "NASPUB"},
    {"name": "phone", "ip": "100.64.0.4", "pub": "PHPUB"},
]


def test_direct_peers_split(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    mesh.add_link(r, "laptop", "phone", NAMES, NOW)
    mesh.set_static(r, "nas", "203.0.113.50:51820", "", NAMES)
    write_observed(r, "2026-11-19T11:59:30Z", [
        {"name": "phone", "endpoint": "85.1.2.3:4000", "handshake_age": 20}])
    managed, static, skipped = mesh.direct_peers(r, "laptop", PEERS, NOW)
    assert [m["name"] for m in managed] == ["nas", "phone"]
    assert [m["name"] for m in static] == ["nas"]
    assert skipped == []


def test_direct_peers_skips_endpointless(r):
    mesh.add_link(r, "laptop", "nas", NAMES, NOW)
    managed, static, skipped = mesh.direct_peers(r, "laptop", PEERS, NOW)
    assert (managed, static, skipped) == ([], [], ["nas"])


# --- rendering -----------------------------------------------------------------

ENV = {"AWG_MESH_HOST": "192.0.2.10", "AWG_MESH_PORT": "443",
       "HUB_IP": "100.64.0.1", "CLIENT_KEEPALIVE": "15-20"}


def test_default_render_unchanged_by_direct_param():
    base = profile.render_client_conf(ENV, "100.64.0.3", "100.64.0.0/24",
                                      "PRIV", "PSK", "SRVPUB")
    assert base == profile.render_client_conf(ENV, "100.64.0.3",
                                              "100.64.0.0/24", "PRIV", "PSK",
                                              "SRVPUB", direct=())
    assert base.count("[Peer]") == 1


def test_direct_peers_rendered_without_psk():
    direct = [{"pub": "NASPUB", "ip": "100.64.0.5",
               "endpoint": "203.0.113.50:51820"}]
    conf = profile.render_client_conf(ENV, "100.64.0.3", "100.64.0.0/24",
                                      "PRIV", "HUBPSK", "SRVPUB", direct)
    hub, nas = conf.split("[Peer]\n")[1:]
    assert "PresharedKey = HUBPSK" in hub
    assert "PublicKey = NASPUB" in nas
    assert "AllowedIPs = 100.64.0.5/32" in nas
    assert "Endpoint = 203.0.113.50:51820" in nas
    assert "PresharedKey" not in nas
    assert "HUBPSK" not in nas


def test_p2p_golden(tmp_path):
    """Byte-exact contract for the Go port (copy the fixture, don't edit)."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(here, "fixtures", "server.env")
    managed = [
        {"pub": "NASPUBNASPUBNASPUBNASPUBNASPUBNASPUBNASPUB0=",
         "ip": "100.64.0.5", "endpoint": "203.0.113.50:51820"},
        {"pub": "PHONEPUBPHONEPUBPHONEPUBPHONEPUBPHONEPUBP0=",
         "ip": "100.64.0.4", "endpoint": "85.1.2.3:4000"},
    ]
    written = profile.generate_p2p_profile(
        env_file=env_file, name="laptop", ip="100.64.0.3", priv="A" * 44,
        pub="B" * 44, psk="C" * 44, managed=managed, static=managed[:1],
        out_prefix=str(tmp_path / "laptop"))
    golden = os.path.join(here, "fixtures", "golden", "laptop-mesh-p2p.conf")
    got = open(written[0]).read()
    if os.environ.get("REGEN_GOLDEN"):
        open(golden, "w").write(got)
    assert got == open(golden).read()
    vpn = profile.decode_profile(open(written[1]).read())
    last = json.loads(vpn["containers"][0]["awg"]["last_config"])
    assert "85.1.2.3:4000" not in last["config"]      # app: static-only
    assert "203.0.113.50:51820" in last["config"]
