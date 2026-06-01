#!/usr/bin/env bash
set -e

cat >> "$PGDATA/postgresql.conf" <<'PGCONF'
listen_addresses = '*'
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
hot_standby = on
synchronous_commit = on
PGCONF

cat >> "$PGDATA/pg_hba.conf" <<'PGHBA'
host replication repl_user 0.0.0.0/0 scram-sha-256
host all all 0.0.0.0/0 scram-sha-256
PGHBA
