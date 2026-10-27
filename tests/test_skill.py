import os

from awg_mesh import skill


def test_load_returns_repo_skill_byte_for_byte():
    with open(os.path.join(os.path.dirname(skill._SKILL), "SKILL.md"),
              encoding="utf-8") as f:
        assert skill.load() == f.read()


def test_load_has_skill_frontmatter():
    text = skill.load()
    assert text.startswith("---\nname: awg-mesh\n")
    assert "description:" in text.split("---", 2)[1]
