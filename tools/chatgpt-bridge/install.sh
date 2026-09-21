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

chmod +x "$HERE/apply-patch.sh" "$HERE/watch-dropbox.sh" "$HERE/audit-local-builds.sh"

mkdir -p "$DROPBOX/_applied" "$DROPBOX/_failed" "$DROPBOX/_logs"
mkdir -p "$LAUNCHD_LOG_DIR"

# convenience CLI on PATH
if mkdir -p "$HOME/bin" && ln -sf "$HERE/apply-patch.sh" "$HOME/bin/chatgpt-patch"; then
  CLI_STATUS="installed"
else
  CLI_STATUS="unavailable (permission denied; the launchd bridge is unaffected)"
  echo "WARNING: could not install ~/bin/chatgpt-patch; continuing with launchd setup" >&2
fi

# launchd cannot execute or read anything under ~/Documents (macOS TCC), so the
# agent goes through ClaudeRunner.app — the bundle that already holds the
# Full Disk Access grant for this fleet. Same pattern as the other orchestrator agents.
APP="/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner"
[ -x "$APP" ] || APP="$HOME/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner"
[ -x "$APP" ] || { echo "ERROR: ClaudeRunner.app not found — run scripts/setup-scheduler.sh first" >&2; exit 1; }
grep -q '\*\.sh ]]' "$(dirname "$(dirname "$APP")")/Resources/launcher.sh" \
  || echo "WARNING: ClaudeRunner launcher lacks .sh support — re-run scripts/setup-scheduler.sh"

LAUNCH_DOMAIN="gui/$(id -u)"
BRIDGE_LOADED=0
launchctl print "$LAUNCH_DOMAIN/$LABEL" >/dev/null 2>&1 && BRIDGE_LOADED=1

AUDIT_LABEL="com.claudeorchestrator.chatgptbridge.audit"
AUDIT_PLIST="$HOME/Library/LaunchAgents/$AUDIT_LABEL.plist"
AUDIT_LOADED=0
launchctl print "$LAUNCH_DOMAIN/$AUDIT_LABEL" >/dev/null 2>&1 && AUDIT_LOADED=1

# Validate a complete replacement before atomically publishing it. Re-running
# setup must never boot out a healthy bridge: launchd will pick up the refreshed
# plist on the next login/reboot, while the currently loaded service stays live.
mkdir -p "$(dirname "$PLIST")"
PLIST_TMP="$(mktemp "${PLIST}.tmp.XXXXXX")"
WD_PLIST_TMP=""
AUDIT_PLIST_TMP=""
cleanup() {
  [ -z "${PLIST_TMP:-}" ] || rm -f "$PLIST_TMP"
  [ -z "${WD_PLIST_TMP:-}" ] || rm -f "$WD_PLIST_TMP"
  [ -z "${AUDIT_PLIST_TMP:-}" ] || rm -f "$AUDIT_PLIST_TMP"
}
trap cleanup EXIT

cat > "$PLIST_TMP" <<PLISTEOF
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

plutil -lint "$PLIST_TMP" >/dev/null
mv "$PLIST_TMP" "$PLIST"
PLIST_TMP=""

if [ "$BRIDGE_LOADED" -eq 1 ]; then
  echo "Bridge already loaded; preserving the live service."
else
  if ! launchctl bootstrap "$LAUNCH_DOMAIN" "$PLIST"; then
    echo "ERROR: launchd could not register $LABEL." >&2
    echo "Run this once in your logged-in Terminal, then re-run setup:" >&2
    echo "  launchctl bootstrap $LAUNCH_DOMAIN '$PLIST'" >&2
    exit 1
  fi
fi
launchctl enable "$LAUNCH_DOMAIN/$LABEL" 2>/dev/null || true

# Keep the deep repository/worktree sweep out of the 30-second intake path. A
# separate agent may take minutes without suppressing patch receipts or bridge
# heartbeats. Its Python worker provides an additional single-writer lock.
AUDIT_PLIST_TMP="$(mktemp "${AUDIT_PLIST}.tmp.XXXXXX")"
cat > "$AUDIT_PLIST_TMP" <<AUDITEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AUDIT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP</string>
    <string>tools/chatgpt-bridge/audit-local-builds.sh</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardOutPath</key><string>$LAUNCHD_LOG_DIR/chatgpt-bridge-audit.out.log</string>
  <key>StandardErrorPath</key><string>$LAUNCHD_LOG_DIR/chatgpt-bridge-audit.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
</dict>
</plist>
AUDITEOF
plutil -lint "$AUDIT_PLIST_TMP" >/dev/null
mv "$AUDIT_PLIST_TMP" "$AUDIT_PLIST"
AUDIT_PLIST_TMP=""
if [ "$AUDIT_LOADED" -eq 1 ]; then
  echo "Deep audit already loaded; preserving the live service."
elif ! launchctl bootstrap "$LAUNCH_DOMAIN" "$AUDIT_PLIST"; then
  echo "ERROR: bridge is loaded, but launchd could not register $AUDIT_LABEL." >&2
  echo "Re-run this installer once from your logged-in Terminal." >&2
  exit 1
fi
launchctl enable "$LAUNCH_DOMAIN/$AUDIT_LABEL" 2>/dev/null || true

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

WD_PLIST_TMP="$(mktemp "${WD_PLIST}.tmp.XXXXXX")"
cat > "$WD_PLIST_TMP" <<WDEOF
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
plutil -lint "$WD_PLIST_TMP" >/dev/null
mv "$WD_PLIST_TMP" "$WD_PLIST"
WD_PLIST_TMP=""

# NB: the watchdog is bootstrapped further down, only AFTER the first heartbeat
# exists — RunAtLoad would otherwise fire a false "bridge is broken" alert during
# the install itself.
WATCHDOG_LOADED=0
launchctl print "$LAUNCH_DOMAIN/$WD_LABEL" >/dev/null 2>&1 && WATCHDOG_LOADED=1

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
echo "  CLI      : $CLI_STATUS"
echo "  launchd  : $LABEL (every 30s)"
echo "  audit    : $AUDIT_LABEL (every 30 min, isolated from intake)"

# ---- prove the agent can actually reach ~/Documents -------------------------
# A silently-denied agent is the failure mode worth catching here: patches would
# sit in the drop-box looking accepted while nothing ever ships. The watcher
# writes a heartbeat on every successful sweep, so wait for one.
echo -n "Verifying the launchd agent can read ~/Documents "
HB="$HOME/Library/Logs/claude-orchestrator/chatgpt-bridge.heartbeat"
heartbeat_is_fresh() {
  [ -f "$HB" ] || return 1
  heartbeat_mtime="$(stat -f %m "$HB" 2>/dev/null || echo 0)"
  heartbeat_now="$(date +%s)"
  heartbeat_age=$((heartbeat_now - heartbeat_mtime))
  [ "$heartbeat_age" -ge 0 ] && [ "$heartbeat_age" -le 90 ]
}

if ! heartbeat_is_fresh; then
  launchctl kickstart "$LAUNCH_DOMAIN/$LABEL" 2>/dev/null || true
fi
for _ in $(seq 1 45); do
  heartbeat_is_fresh && break
  echo -n "."
  sleep 1
done
echo
if heartbeat_is_fresh; then
  echo "  ✓ agent healthy — drop a patch in $DROPBOX and it will ship"
  rm -f "$WD_DIR/.last-alert"
  if [ "$WATCHDOG_LOADED" -eq 1 ]; then
    echo "  ✓ watchdog already armed ($WD_LABEL, every 5 min)"
  elif launchctl bootstrap "$LAUNCH_DOMAIN" "$WD_PLIST"; then
    launchctl enable "$LAUNCH_DOMAIN/$WD_LABEL" 2>/dev/null || true
    echo "  ✓ watchdog armed ($WD_LABEL, every 5 min)"
  else
    echo "  ✗ bridge is healthy, but launchd could not register its watchdog." >&2
    echo "    Run this once in your logged-in Terminal, then re-run setup:" >&2
    echo "      launchctl bootstrap $LAUNCH_DOMAIN '$WD_PLIST'" >&2
    exit 1
  fi
else
  echo "  ✗ agent could NOT read ~/Documents."
  echo "    Grant Full Disk Access to ClaudeRunner.app, then re-run this script:"
  echo "      System Settings → Privacy & Security → Full Disk Access → + → $(dirname "$(dirname "$APP")")"
  echo "    Until then the drop-box is inert. 'chatgpt-patch <file>' from a terminal still works."
  exit 1
fi
