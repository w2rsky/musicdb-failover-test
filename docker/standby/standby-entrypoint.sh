#!/usr/bin/env bash
set -euo pipefail

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Initializing standby from master..."

  mkdir -p "$PGDATA"
  rm -rf "$PGDATA"/*

  until pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U postgres; do
    echo "Waiting for master..."
    sleep 2
  done

  export PGPASSWORD="$REPLICATION_PASSWORD"

  pg_basebackup \
    -h "$PRIMARY_HOST" \
    -p "$PRIMARY_PORT" \
    -U "$REPLICATION_USER" \
    -D "$PGDATA" \
    -Fp \
    -Xs \
    -P \
    -C \
    -S standby_slot

  touch "$PGDATA/standby.signal"

  cat > "$PGDATA/postgresql.auto.conf" <<PGCONF
primary_conninfo = 'host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPLICATION_USER password=$REPLICATION_PASSWORD application_name=pg_standby'
primary_slot_name = 'standby_slot'
hot_standby = 'on'
PGCONF

  chown -R postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"
fi

exec docker-entrypoint.sh postgres
