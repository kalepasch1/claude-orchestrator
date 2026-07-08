#!/bin/zsh
# ============================================================================
# setup-second-runner.sh — Set up a parallel runner on a second Mac
# ============================================================================
# Run this script ON THE SECOND MAC after cloning the repo.
#
# Prerequisites:
#   1. Clone the repo:  git clone <repo-url> ~/Documents/beethoven/claude-orchestrator
#   2. Install Python deps:  cd runner && pip3 install pyyaml --break-system-packages
#   3. Install Claude CLI:  brew install claude (or however you installed it on Mac #1)
#   4. Auth Claude CLI:  claude login  (use one of the 3 Max accounts)
#   5. Copy .env from Mac #1:  scp mac1:~/Documents/beethoven/claude-orchestrator/runner/.env ./runner/.env
#   6. Run this script:  zsh runner/setup-second-runner.sh
#
# How it works:
#   - The runner uses atomic Supabase claims (UPDATE ... WHERE status='QUEUED' RETURNING)
#     so two runners NEVER claim the same task.
#   - Each runner has a unique ORCH_MACHINE_ID derived from its hostname.
#   - The autoscale_signal module detects multi-machine fleet and adjusts recommendations.
#   - The resource governor on each Mac independently manages its own RAM/disk.
# ============================================================================

set -euo pipefail

RUNNER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$RUNNER_DIR/.." && pwd)"

echo "=== Claude Orchestrator — Second Runner Setup ==="
echo ""

# 1. Verify .env exists
if [[ ! -f "$RUNNER_DIR/.env" ]]; then
    echo "ERROR: $RUNNER_DIR/.env not found."
    echo "Copy it from your primary Mac first:"
    echo "  scp mac1:~/Documents/beethoven/claude-orchestrator/runner/.env $RUNNER_DIR/.env"
    exit 1
fi

# 2. Set unique machine ID (prevents lock collisions)
MACHINE_ID="runner-$(hostname -s | tr '[:upper:]' '[:lower:]')"
if ! grep -q "ORCH_MACHINE_ID" "$RUNNER_DIR/.env"; then
    echo "" >> "$RUNNER_DIR/.env"
    echo "# ── Multi-machine fleet identity ──────────────────────────────────────────" >> "$RUNNER_DIR/.env"
    echo "ORCH_MACHINE_ID=$MACHINE_ID" >> "$RUNNER_DIR/.env"
    echo "Added ORCH_MACHINE_ID=$MACHINE_ID to .env"
else
    echo "ORCH_MACHINE_ID already set in .env"
fi

# 3. Verify Claude CLI is available
if ! command -v claude &>/dev/null; then
    echo "ERROR: 'claude' CLI not found in PATH."
    echo "Install it and run 'claude login' with one of your Max accounts."
    exit 1
fi
echo "Claude CLI: $(which claude)"

# 4. Verify Python3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    exit 1
fi
echo "Python: $(python3 --version)"

# 5. Verify pyyaml
python3 -c "import yaml" 2>/dev/null || {
    echo "Installing pyyaml..."
    pip3 install pyyaml --break-system-packages
}

# 6. Test Supabase connectivity
echo -n "Testing Supabase connection... "
python3 -c "
import os, sys
sys.path.insert(0, '$RUNNER_DIR')
from dotenv import load_dotenv
load_dotenv('$RUNNER_DIR/.env')
import urllib.request, json
url = os.environ['SUPABASE_URL'] + '/rest/v1/projects?select=name&limit=1'
req = urllib.request.Request(url, headers={
    'apikey': os.environ['SUPABASE_SERVICE_KEY'],
    'Authorization': 'Bearer ' + os.environ['SUPABASE_SERVICE_KEY']
})
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
print(f'OK ({len(data)} projects)')
" 2>/dev/null || {
    # Try without dotenv
    python3 -c "
import os, sys, urllib.request, json
sys.path.insert(0, '$RUNNER_DIR')
# Source .env manually
for line in open('$RUNNER_DIR/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
url = os.environ.get('SUPABASE_URL','') + '/rest/v1/projects?select=name&limit=1'
req = urllib.request.Request(url, headers={
    'apikey': os.environ.get('SUPABASE_SERVICE_KEY',''),
    'Authorization': 'Bearer ' + os.environ.get('SUPABASE_SERVICE_KEY','')
})
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
print(f'OK ({len(data)} projects)')
" 2>/dev/null || echo "FAILED (check SUPABASE_URL and SUPABASE_SERVICE_KEY in .env)"
}

# 7. Create launchd plist for auto-start
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.claudeorchestrator.runner.plist"
mkdir -p "$PLIST_DIR"

cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claudeorchestrator.runner</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>$RUNNER_DIR/keepalive.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$RUNNER_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/claude-orchestrator/runner-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/claude-orchestrator/runner-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Created launchd plist: $PLIST_FILE"
echo "Machine ID: $MACHINE_ID"
echo ""
echo "To start the runner NOW:"
echo "  launchctl load $PLIST_FILE"
echo ""
echo "To start manually (foreground):"
echo "  cd $RUNNER_DIR && zsh keepalive.sh"
echo ""
echo "To check status:"
echo "  launchctl list | grep claude"
echo "  tail -f ~/Library/Logs/claude-orchestrator/runner.log"
echo ""
echo "To stop:"
echo "  launchctl unload $PLIST_FILE"
