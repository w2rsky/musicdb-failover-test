#!/usr/bin/env bash
set -euo pipefail

echo "Writing test events to master..."
./scripts/workload.sh master 5

echo
echo "Stopping master to simulate node failure..."
docker stop pg_master

echo
echo "Running failover agent once..."
python3 agent/agent.py standby --once

echo
echo "Writing test events to promoted standby..."
./scripts/workload.sh standby 5

echo
echo "Final standby status:"
docker exec -u postgres pg_standby psql -U postgres -d musicdb -c "
SELECT pg_is_in_recovery() AS still_in_recovery;
SELECT count(*) AS playback_events FROM playback_events;
"
