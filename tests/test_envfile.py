import pytest

from awg_mesh import MeshError, envfile


def test_parse_comments_blank_lines_and_spacing(tmp_path):
    p = tmp_path / "server.env"
    p.write_text("# comment\n\nKEY1=value1\nKEY2 = spaced \nKEY3=a=b\n")
    env = envfile.load(str(p))
    assert env["KEY1"] == "value1"
    assert env["KEY2"] == "spaced"
    assert env["KEY3"] == "a=b"
    assert "comment" not in env


def test_missing_file_raises_mesh_error(tmp_path):
    with pytest.raises(MeshError):
        envfile.load(str(tmp_path / "nope.env"))


def test_values_are_data_never_executed(tmp_path):
    # The old bash CLI sourced server.env; a tampered file could run code.
    p = tmp_path / "server.env"
    marker = tmp_path / "pwned"
    p.write_text(f"EVIL=$(touch {marker})\nOTHER=1\n")
    env = envfile.load(str(p))
    assert env["EVIL"] == f"$(touch {marker})"  # stored verbatim
    assert not marker.exists()


def test_get_returns_default_for_missing_or_empty():
    assert envfile.get({}, "MISSING", "dflt") == "dflt"
    assert envfile.get({"K": ""}, "K", "dflt") == "dflt"
    assert envfile.get({"K": "v"}, "K", "dflt") == "v"
