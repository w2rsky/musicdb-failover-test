#!/usr/bin/env bash
set -euo pipefail

echo "Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo
echo "Master replication status:"
docker exec -u postgres pg_master psql -U postgres -d musicdb -c \
"SELECT application_name, state, sync_state, client_addr FROM pg_stat_replication;" || true

echo
echo "Standby recovery status:"
docker exec -u postgres pg_standby psql -U postgres -d musicdb -c \
"SELECT pg_is_in_recovery();" || true
