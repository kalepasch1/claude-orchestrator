#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  Weekend Full-Throttle Configuration"
echo "========================================"
echo ""

# 1. Clean stale keepalive lock files
echo "==> Step 1: Cleaning stale keepalive locks..."
rm -rf .runtime/keepalive.lock.stale.* 2>/dev/null || true
echo "   Cleaned $(ls -d .runtime/keepalive.lock.stale.* 2>/dev/null | wc -l | tr -d ' ') remaining (should be 0)"
echo ""

# 2. Clean stale git locks
echo "==> Step 2: Cleaning stale git locks..."
rm -f .git/index.lock .git/HEAD.lock
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "   Done."
echo ""

# 3. Push .env changes (drain off, ceiling raised)
echo "==> Step 3: Committing .env and backlog changes..."
git add -A
git commit -m "weekend full-throttle: drain off, ceiling 25, lean off, XAPI_KEY newline fix, queue darwin backlog" || echo "   (nothing to commit)"
git push origin master
echo "   Done."
echo ""

# 4. Push fleet-wide config
echo "==> Step 4: Pushing fleet config..."
cd runner
python3 fleetctl.py set MAX_PARALLEL_CEILING 25
python3 fleetctl.py set MAX_PARALLEL 25
python3 fleetctl.py set ORCH_DRAIN_MODE false
python3 fleetctl.py set ORCH_LEAN_MODE false
python3 fleetctl.py set PER_TASK_GB 0.5
echo "   Done."
echo ""

# 5. Restart all runners to pick up new .env
echo "==> Step 5: Restarting fleet runners..."
python3 fleetctl.py restart all
echo "   Done."
echo ""

# 6. Pull latest code on all machines
echo "==> Step 6: Triggering git pull on fleet..."
python3 fleetctl.py pull all
echo "   Done."
echo ""

# 7. Fleet status check
echo "==> Step 7: Fleet status..."
python3 fleetctl.py status
echo ""

echo "========================================"
echo "  Full throttle engaged!"
echo "  The fleet will restart with:"
echo "    - DRAIN_MODE=false (generators unblocked)"
echo "    - LEAN_MODE=false"
echo "    - MAX_PARALLEL=25 (up from 15)"
echo "    - PER_TASK_GB=0.5"
echo "    - Darwin Kernel backlog queued"
echo "========================================"
read -p "Press Enter to close..."
