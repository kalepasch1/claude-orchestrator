#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  Claude-Orchestrator Fix Finalization"
echo "========================================"
echo ""

# 1. Clean up stale git lock files
echo "==> Step 1: Cleaning stale git lock files..."
rm -f .git/index.lock .git/HEAD.lock
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "   Done."
echo ""

# 2. Push the resource_governor + fleet fix commit
echo "==> Step 2: Pushing resource_governor + fleet fix commit..."
git push origin master
echo "   Done."
echo ""

# 3. Push PER_TASK_GB=0.5 centrally via fleetctl
echo "==> Step 3: Pushing PER_TASK_GB=0.5 to fleet config..."
cd runner
python3 fleetctl.py set PER_TASK_GB 0.5
echo "   Done."
echo ""

# 4. Check fleet status
echo "==> Step 4: Checking fleet status..."
python3 fleetctl.py status
echo ""

echo "========================================"
echo "  All done! You can close this window."
echo "========================================"
read -p "Press Enter to close..."
