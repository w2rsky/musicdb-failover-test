#!/usr/bin/env bash
set -euo pipefail

docker compose down -v
echo "Cluster volumes removed. Run: docker compose up -d"
