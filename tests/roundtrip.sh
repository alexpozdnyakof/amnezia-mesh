#!/usr/bin/env bash
# Self-test: roundtrip a real Amnezia vpn:// profile through our codec.
# Usage: tests/roundtrip.sh [profile.vpn ...]   (defaults to none — pass files)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

[ $# -ge 1 ] || { echo "usage: $0 <profile.vpn> [...]" >&2; exit 2; }
rc=0
for f in "$@"; do
  python3 "$ROOT/lib/profile.py" roundtrip "$f" || rc=1
done
exit "$rc"
