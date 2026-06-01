#!/usr/bin/env bash
set -euo pipefail

REQUESTS="${REQUESTS:-100000}"
CONCURRENCY="${CONCURRENCY:-200}"
FAULT="${FAULT:-master_crash}"

MODES=(
  off
  local
  remote_write
  on
  remote_apply
)

mkdir -p reports

echo "Part 2 verification matrix"
echo "requests=$REQUESTS"
echo "concurrency=$CONCURRENCY"
echo "fault=$FAULT"

for mode in "${MODES[@]}"; do
  echo
  echo "=================================================="
  echo "Running synchronous_commit=$mode"
  echo "=================================================="

  log_file="reports/part2_${mode}_${FAULT}.log"

  set +e
  python scripts/part2_verify.py \
    --reset-cluster \
    --requests "$REQUESTS" \
    --concurrency "$CONCURRENCY" \
    --synchronous-commit "$mode" \
    --fault "$FAULT" \
    2>&1 | tee "$log_file"

  status="${PIPESTATUS[0]}"
  set -e

  if [ "$status" -eq 0 ]; then
    echo "RESULT mode=$mode status=PASSED log=$log_file"
  else
    echo "RESULT mode=$mode status=FAILED log=$log_file"
  fi
done
