"""docker compose wrapper.

server.env values are passed as the compose process environment, mirroring
the old `set -a; . server.env; docker compose ...` dance.
"""
import os
import subprocess


def compose(root, env, *args, input_text=None):
    full_env = dict(os.environ)
    full_env.update(env)
    return subprocess.run(["docker", "compose", *args],
                          cwd=root, env=full_env, input=input_text,
                          text=True, capture_output=True)
