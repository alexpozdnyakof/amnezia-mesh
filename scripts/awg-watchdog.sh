#!/bin/bash
# amnezia-mesh watchdog (install via: awg-mesh monitoring install)
LOG=/var/log/amnezia-mesh-watchdog.log
CONTAINER=${AWG_MESH_CONTAINER:-amnezia-mesh-awg}
if ! docker ps --filter name="^/$CONTAINER$" --format '{{.Names}}' | grep -q "$CONTAINER"; then
  echo "$(date -Is) $CONTAINER down, restarting" >> "$LOG"
  docker start "$CONTAINER" >> "$LOG" 2>&1
elif ! timeout 10 docker exec "$CONTAINER" awg show >/dev/null 2>&1; then
  echo "$(date -Is) $CONTAINER wedged, restarting" >> "$LOG"
  docker restart "$CONTAINER" >> "$LOG" 2>&1
fi
