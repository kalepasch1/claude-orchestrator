#!/usr/bin/env bash
# One-shot orchestrator-runner setup for an always-on cloud VM (Oracle Ampere / Ubuntu / Oracle Linux).
# Prereqs on the VM before running:
#   1) gh authenticated (run: gh auth login)  — needed to clone the private repo + push/deploy
#   2) runner/.env copied to the VM (scp from your Mac) at ~/claude-orchestrator/runner/.env
# Usage on the VM:  bash vm-setup.sh
set -euo pipefail
REPO="https://github.com/kalepasch1/claude-orchestrator.git"
DEST="${DEST:-$HOME/claude-orchestrator}"

echo "== installing deps =="
if command -v dnf >/dev/null 2>&1; then sudo dnf install -y git gh python3-pip
elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y git gh python3-pip
fi

echo "== cloning =="
if [ ! -d "$DEST/.git" ]; then git clone "$REPO" "$DEST"; else (cd "$DEST" && git pull --ff-only || true); fi

echo "== python deps (best-effort; add any missing module the log reports) =="
pip3 install --user --upgrade supabase anthropic requests python-dotenv || true

echo "== env check =="
if [ ! -f "$DEST/runner/.env" ]; then
  echo "!! MISSING $DEST/runner/.env — scp it from your Mac first, then re-run. Aborting."; exit 1; fi
grep -q '^ORCH_PUSH_ON_MERGE='   "$DEST/runner/.env" || echo 'ORCH_PUSH_ON_MERGE=true'   >> "$DEST/runner/.env"
grep -q '^ENABLE_PROACTIVE_LOOPS=' "$DEST/runner/.env" || echo 'ENABLE_PROACTIVE_LOOPS=true' >> "$DEST/runner/.env"

echo "== systemd unit (path-patched to $DEST) =="
sed "s#/opt/claude-orchestrator#$DEST#g" "$DEST/deploy/runner.service" | sudo tee /etc/systemd/system/orchestrator-runner.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now orchestrator-runner

echo "== done =="
echo "Logs:   journalctl -u orchestrator-runner -f"
echo "NOTE: to DEPLOY each app from this VM, also clone the app repos here and update projects.repo_path"
echo "      to their VM paths (or clone them to the same paths the projects table already lists)."
