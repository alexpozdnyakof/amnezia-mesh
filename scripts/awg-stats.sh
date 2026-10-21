#!/bin/bash
# amnezia-mesh stats logger (install via: awg-mesh monitoring install)
LOG=/var/log/amnezia-mesh-stats.log
CONTAINER=${AWG_MESH_CONTAINER:-amnezia-mesh-awg}
echo "=== $(date -Is) ===" >> "$LOG"
docker exec "$CONTAINER" awg show 2>&1 | grep -E "peer:|endpoint|latest handshake|transfer" >> "$LOG"
if [ "$(wc -l < "$LOG")" -gt 30000 ]; then tail -30000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
