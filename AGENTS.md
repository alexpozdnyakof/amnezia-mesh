# amnezia-mesh — orientation for agents

Self-hosted WireGuard mesh with AmneziaWG obfuscation and MagicDNS; CLI +
rendered configs + docker compose. Python, stdlib only. The canonical
implementation going forward is the Go port in the sibling repo
`amnezia-mesh-go`; this repo stays the frozen reference (byte parity is the
contract).

## Work with the CLI

Run from the repo root: `.venv/bin/python -m awg_mesh ...` (or
`./bin/awg-mesh`). Everything scriptable: `--json`, `AWG_MESH_NONINTERACTIVE=1`,
`AWG_MESH_ROOT=/path`. Human/AI operator guide lives in
`skills/awg-mesh/SKILL.md` — the same file `awg-mesh skill` prints and
`awg-mesh skill --install` copies to `~/.agents/skills/`.

## Commands for this repo

```sh
.venv/bin/python -m pytest tests/          # test suite (golden fixtures = contract)
.venv/bin/python -m pytest tests/ -k render
```

Golden fixtures under `tests/fixtures/golden/` are byte-exact render
outputs; any intentional render change regenerates them and updates
`awg_mesh/render.py` + tests together.

## Hard rules

- **Never touch the production server** (`amnezia-mesh-awg` /
  `amnezia-mesh-dns` containers or its `config/`) from this repo's
  development work. Live experiments go to the parallel stand described in
  `../amnezia-mesh-go/docs/parity-live.md`.
- The Go port must stay byte-parity with this CLI; if you change behavior,
  mirror the change in `../amnezia-mesh-go` and re-run its parity harness.
