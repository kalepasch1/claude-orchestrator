#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  Fix push — remove .env from commit"
echo "========================================"
echo ""

# 1. Clean stale keepalive locks
echo "==> Step 1: Cleaning stale keepalive locks..."
rm -rf .runtime/keepalive.lock.stale.* 2>/dev/null || true
echo "   Done."
echo ""

# 2. Unstage secret-containing files from the commit
echo "==> Step 2: Removing secret-containing files from commit..."
git reset HEAD~1 --soft

# Add gitignore entries for .env backup/merge files
grep -q '\.env\.pre-symlink' .gitignore 2>/dev/null || echo 'runner/.env.pre-symlink-merge-*' >> .gitignore
grep -q '\.env\.bak' .gitignore 2>/dev/null || true

# Delete the leaked backup file from the worktree
rm -f runner/.env.pre-symlink-merge-* 2>/dev/null || true

# Re-stage everything EXCEPT .env files
git add -A
git reset HEAD runner/.env 2>/dev/null || true
git reset HEAD 'runner/.env.pre-symlink-merge-*' 2>/dev/null || true

# Verify no .env files are staged
echo "   Staged .env files (should be empty):"
git diff --cached --name-only | grep '\.env' || echo "   (none - good)"

git commit -m "weekend full-throttle: queue darwin backlog, clean up stale scripts"
echo "   Done."
echo ""

# 3. Push
echo "==> Step 3: Pushing to GitHub..."
git push origin master
echo "   Done."
echo ""

# 4. Push fleet-wide config via fleetctl (these go to Supabase, not git)
echo "==> Step 4: Pushing fleet config..."
cd runner
python3 fleetctl.py set MAX_PARALLEL_CEILING 25
python3 fleetctl.py set MAX_PARALLEL 25
python3 fleetctl.py set ORCH_DRAIN_MODE false
python3 fleetctl.py set ORCH_LEAN_MODE false
python3 fleetctl.py set PER_TASK_GB 0.5
echo "   Done."
echo ""

# 5. Restart all runners to pick up config
echo "==> Step 5: Restarting fleet..."
python3 fleetctl.py restart all
echo "   Done."
echo ""

# 6. Pull latest on fleet
echo "==> Step 6: Triggering git pull on fleet..."
python3 fleetctl.py pull all
echo "   Done."
echo ""

# 7. Status
echo "==> Step 7: Fleet status..."
python3 fleetctl.py status
echo ""

echo "========================================"
echo "  Full throttle engaged!"
echo "========================================"
read -p "Press Enter to close..."
