#!/usr/bin/env bash
# catchup_drive.sh — supervised merge-train catch-up (operator, 2026-07-31).
# Boosted per-pass caps; verify/test gates still judge every branch. Stops when
# two consecutive passes merge nothing (backlog exhausted) or after MAX_PASSES.
cd "$(dirname "$0")"
export MERGE_TRAIN_LOW_RISK_BATCH=120
export MERGE_TRAIN_STANDARD_BATCH=60
export MERGE_TRAIN_SENSITIVE_BATCH=8
export MERGE_TRAIN_SCAN_PER_PROJECT=1500
export MERGE_TRAIN_PROJECT_WORKERS=8
MAX_PASSES=${MAX_PASSES:-40}
ZERO_STREAK=0
for i in $(seq 1 $MAX_PASSES); do
  echo "=== catchup pass $i/$MAX_PASSES $(date '+%H:%M:%S') ==="
  OUT=$(python3 merge_train.py 2>&1 | grep -va MallocStack)
  SUMMARY=$(echo "$OUT" | grep -a "merged," | tail -1)
  echo "$SUMMARY"
  MERGED=$(echo "$SUMMARY" | grep -oE "[0-9]+ merged" | grep -oE "[0-9]+")
  if [ "${MERGED:-0}" = "0" ]; then
    ZERO_STREAK=$((ZERO_STREAK+1))
    [ $ZERO_STREAK -ge 2 ] && echo "=== backlog exhausted (2 zero passes) ===" && break
  else
    ZERO_STREAK=0
  fi
  # convert redos/testfails faster between passes
  python3 auto_remediate.py >/dev/null 2>&1 || true
  sleep 2
done
echo "=== catchup drive complete $(date '+%H:%M:%S') ==="
