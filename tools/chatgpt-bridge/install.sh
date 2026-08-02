#!/bin/bash
# install.sh — one-time setup for the ChatGPT → GitHub bridge.
# Idempotent: safe to re-run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DROPBOX="$HOME/Documents/chatgpt-dropbox"
PLIST="$HOME/Library/LaunchAgents/com.claudeorchestrator.chatgptbridge.plist"
LABEL="com.claudeorchestrator.chatgptbridge"
# launchd opens StandardOutPath/StandardErrorPath ITSELF, before it execs the
# program — so those two paths are opened as launchd, not as ClaudeRunner.app,
# and the app's Full Disk Access grant does NOT cover them. Any path under
# ~/Documents therefore fails to open and launchd aborts the spawn with
# EX_CONFIG (exit 78) without ever running the job. Keep them under ~/Library.
LAUNCHD_LOG_DIR="$HOME/Library/Logs/claude-orchestrator"

chmod +x "$HERE/apply-patch.sh" "$HERE/watch-dropbox.sh"

mkdir -p "$DROPBOX/_applied" "$DROPBOX/_failed" "$DROPBOX/_logs"
mkdir -p "$LAUNCHD_LOG_DIR"

# convenience CLI on PATH
mkdir -p "$HOME/bin"
ln -sf "$HERE/apply-patch.sh" "$HOME/bin/chatgpt-patch"

# launchd cannot execute or read anything under ~/Documents (macOS TCC), so the
# agent goes through ClaudeRunner.app — the bundle that already holds the
# Full Disk Access grant for this fleet. Same pattern as the other orchestrator agents.
APP="/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner"
[ -x "$APP" ] || APP="$HOME/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner"
[ -x "$APP" ] || { echo "ERROR: ClaudeRunner.app not found — run scripts/setup-scheduler.sh first" >&2; exit 1; }
grep -q '\*\.sh ]]' "$(dirname "$(dirname "$APP")")/Resources/launcher.sh" \
  || echo "WARNING: ClaudeRunner launcher lacks .sh support — re-run scripts/setup-scheduler.sh"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP</string>
    <string>tools/chatgpt-bridge/watch-dropbox.sh</string>
  </array>
  <key>StartInterval</key><integer>30</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LAUNCHD_LOG_DIR/chatgpt-bridge.out.log</string>
  <key>StandardErrorPath</key><string>$LAUNCHD_LOG_DIR/chatgpt-bridge.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL" 2>/dev/null || true

# ---- watchdog -------------------------------------------------------------
# Lives outside ~/Documents on purpose: when the FDA grant is lost, everything
# under ~/Documents is unreadable, so the bridge can neither run nor report it.
# The watchdog only needs ~/Library, which is always reachable.
WD_DIR="$HOME/Library/Application Support/chatgpt-bridge"
WD_LABEL="com.claudeorchestrator.chatgptbridge.watchdog"
WD_PLIST="$HOME/Library/LaunchAgents/$WD_LABEL.plist"
mkdir -p "$WD_DIR" "$HOME/Library/Logs/claude-orchestrator"
cp "$HERE/watchdog.sh" "$WD_DIR/watchdog.sh"
chmod +x "$WD_DIR/watchdog.sh"

cat > "$WD_PLIST" <<WDEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$WD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WD_DIR/watchdog.sh</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/claude-orchestrator/chatgpt-bridge-watchdog.err</string>
  <key>EnvironmentVariables</key>
  <dict><key>HOME</key><string>$HOME</string></dict>
</dict>
</plist>
WDEOF

# NB: the watchdog is bootstrapped further down, only AFTER the first heartbeat
# exists — RunAtLoad would otherwise fire a false "bridge is broken" alert during
# the install itself.
launchctl bootout "gui/$(id -u)/$WD_LABEL" 2>/dev/null || true

cat > "$DROPBOX/README.txt" <<'EOF'
ChatGPT → GitHub drop-box
=========================

Drop a patch here and it lands on GitHub automatically (checked every 30s).

Accepted files:  .patch  .diff  .zip  .tar.gz

Naming (this is how the repo is chosen):
    <repo>--<short-slug>.patch
e.g. tomorrow--fix-login-redirect.patch
     claude-orchestrator--add-retry.patch

Known repos: claude-orchestrator, tomorrow, apparently, smarter, illuminati, vigil, 2080

Optional header lines inside a .patch/.diff:
    # repo: tomorrow
    # message: fix: login redirect loop on Safari

What happens:
  new branch chatgpt/<slug>-<time> off the default branch
  -> commit authored as kalepasch1 <kalepasch@gmail.com>  (Vercel requires this)
  -> pushed, PR opened, macOS notification with the PR link

Results:  _applied/   _failed/ (with .error.txt)   _logs/bridge.log

Manual run:  chatgpt-patch ~/Downloads/tomorrow--thing.patch
EOF

echo "Installed."
echo "  drop-box : $DROPBOX"
echo "  CLI      : ~/bin/chatgpt-patch"
echo "  launchd  : $LABEL (every 30s)"

# ---- prove the agent can actually reach ~/Documents -------------------------
# A silently-denied agent is the failure mode worth catching here: patches would
# sit in the drop-box looking accepted while nothing ever ships. The watcher
# writes a heartbeat on every successful sweep, so wait for one.
echo -n "Verifying the launchd agent can read ~/Documents "
HB="$HOME/Library/Logs/claude-orchestrator/chatgpt-bridge.heartbeat"
rm -f "$HB"
launchctl kickstart "gui/$(id -u)/$LABEL" 2>/dev/null || true
for _ in $(seq 1 20); do
  [ -f "$HB" ] && break
  echo -n "."
  sleep 1
done
echo
if [ -f "$HB" ]; then
  echo "  ✓ agent healthy — drop a patch in $DROPBOX and it will ship"
  rm -f "$WD_DIR/.last-alert"
  launchctl bootstrap "gui/$(id -u)" "$WD_PLIST"
  launchctl enable "gui/$(id -u)/$WD_LABEL" 2>/dev/null || true
  echo "  ✓ watchdog armed ($WD_LABEL, every 5 min)"
else
  echo "  ✗ agent could NOT read ~/Documents."
  echo "    Grant Full Disk Access to ClaudeRunner.app, then re-run this script:"
  echo "      System Settings → Privacy & Security → Full Disk Access → + → $(dirname "$(dirname "$APP")")"
  echo "    Until then the drop-box is inert. 'chatgpt-patch <file>' from a terminal still works."
  exit 1
fi
