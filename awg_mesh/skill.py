"""Bundled agent skill: `awg-mesh skill` prints the SKILL.md shipped in
this repo, `awg-mesh skill --install` copies it where coding agents look
for skills (~/.agents/skills/)."""
import os
import shutil

_SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "skills", "awg-mesh", "SKILL.md")


def load():
    with open(_SKILL, encoding="utf-8") as f:
        return f.read()


def install():
    dest = os.path.expanduser(os.path.join("~", ".agents", "skills", "awg-mesh"))
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, "SKILL.md")
    shutil.copyfile(_SKILL, path)
    return path
