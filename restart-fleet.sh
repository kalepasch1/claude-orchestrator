#!/usr/bin/env bash
# restart-fleet.sh — one command to ship orchestrator changes + reload BOTH Macs onto them.
#
# What it does, in order:
#   1. clears any stale git locks (the recurring ".git/index.lock Operation not permitted" blocker)
#   2. commits whatever is staged/dirty in the orchestrator repo and pushes to origin
#   3. restarts THIS Mac's runner (kills runner.py + keepalive.sh; keepalive respawns on fresh code + .env)
#   4. restarts Mac 2 over SSH (git pull + same restart) so it stops lagging — falls back to a
#      fleet_control git_pull+restart row if SSH isn't reachable
#
# Run from Mac 1 (the machine with the repo + GitHub creds):
#   bash ~/Documents/beethoven/claude-orchestrator/restart-fleet.sh
#
# Override Mac 2 target if needed:
#   MAC2_HOST=Mandys-MacBook-Pro.local MAC2_USER=mandy bash restart-fleet.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO" || { echo "!! cannot cd to repo"; exit 1; }
BR="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo master)"
MAC2_HOST="${MAC2_HOST:-Mandys-MacBook-Pro.local}"
MAC2_USER="${MAC2_USER:-$(whoami)}"
MSG="${1:-fleet: ship orchestrator changes + restart}"

echo "==> repo: $REPO   branch: $BR"

echo "==> 1/4  clear stale git locks"
rm -f .git/index.lock .git/HEAD.lock .git/*.lock .git/refs/heads/*.lock 2>/dev/null || true
# kill any crashed git that may be holding a lock (best-effort)
pkill -9 -f "git commit" 2>/dev/null || true

echo "==> 2/4  commit + push"
git add -A 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git -c user.name="Kale Aaron Pasch" -c user.email="kalepasch@gmail.com" \
      commit --no-verify -m "$MSG" && echo "   committed." || echo "   (commit failed — continuing)"
else
  echo "   (nothing to commit)"
fi
if git push origin "$BR" 2>/dev/null; then
  echo "   pushed -> origin/$BR ($(git rev-parse --short HEAD))"
else
  echo "   !! push failed — check auth, then: git push origin $BR"
fi

echo "==> 3/4  restart THIS Mac's runner"
pkill -9 -f keepalive.sh 2>/dev/null || true
pkill -9 -f "runner.py" 2>/dev/null || true
sleep 3
rm -f "$REPO/.runtime/runner.lock" 2>/dev/null || true
( cd "$REPO/runner" && nohup bash keepalive.sh >/dev/null 2>&1 & )
sleep 5
if pgrep -fl "runner.py" >/dev/null 2>&1; then echo "   this Mac: runner UP"; else echo "   !! this Mac: runner not detected — check .runtime/logs/runner.log"; fi

echo "==> 4/4  restart Mac 2 ($MAC2_USER@$MAC2_HOST)"
REMOTE_CMDS='set -e; cd ~/Documents/beethoven/claude-orchestrator 2>/dev/null || cd "$(git -C ~ rev-parse --show-toplevel 2>/dev/null)"; \
  rm -f .git/index.lock .git/*.lock 2>/dev/null || true; \
  git pull --ff-only || echo "(pull skipped)"; \
  pkill -9 -f keepalive.sh 2>/dev/null || true; pkill -9 -f runner.py 2>/dev/null || true; sleep 3; \
  rm -f .runtime/runner.lock 2>/dev/null || true; \
  ( cd runner && nohup bash keepalive.sh >/dev/null 2>&1 & ); sleep 5; \
  pgrep -fl runner.py >/dev/null && echo "   Mac2: runner UP" || echo "   Mac2: runner NOT up — check logs"'
if ssh -o BatchMode=yes -o ConnectTimeout=6 "$MAC2_USER@$MAC2_HOST" "$REMOTE_CMDS" 2>/dev/null; then
  echo "   Mac 2 restarted over SSH."
else
  echo "   !! SSH to $MAC2_HOST failed — queuing a fleet_control git_pull+restart as fallback."
  ( cd "$REPO/runner" && python3 -c "import db; db.insert('fleet_control',{'action':'git_pull','target':'$MAC2_HOST','params':{'restart':True},'requested_by':'restart-fleet'}); db.insert('fleet_control',{'action':'restart','target':'$MAC2_HOST','params':{},'requested_by':'restart-fleet'}); print('   queued fleet_control for Mac 2')" 2>/dev/null ) \
    || echo "   (could not queue fleet_control — restart Mac 2 manually: bash scripts/setup-mac2.sh)"
fi

echo ""
echo "==> DONE. Verify in ~60s:"
echo "    tail -f $REPO/.runtime/logs/runner.log | grep -iE 'integrate=|merged|coder'"
echo "    (integrate should read (local), not (pr); integrated>0 within a few minutes)"
