#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-master}"
COUNT="${2:-10}"

if [ "$TARGET" = "master" ]; then
  CONTAINER="pg_master"
elif [ "$TARGET" = "standby" ]; then
  CONTAINER="pg_standby"
else
  echo "Usage: ./scripts/workload.sh master|standby [count]"
  exit 1
fi

for i in $(seq 1 "$COUNT"); do
  docker exec -u postgres "$CONTAINER" psql -U postgres -d musicdb -c "
    INSERT INTO playback_events(listener_id, track_id, device, played_ms, completed)
    SELECT
      (floor(random() * 100) + 1)::int,
      (floor(random() * 200) + 1)::int,
      (ARRAY['ios', 'android', 'web', 'smart_speaker'])[(floor(random() * 4) + 1)::int],
      (floor(random() * 240000) + 1000)::int,
      random() > 0.15;
  " >/dev/null

  echo "Inserted playback event $i into $TARGET"
done
