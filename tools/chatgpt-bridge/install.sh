#!/bin/bash
# install.sh — one-time setup for the ChatGPT → GitHub bridge.
# Idempotent: safe to re-run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DROPBOX="$HOME/Documents/chatgpt-dropbox"
PLIST="$HOME/Library/LaunchAgents/com.claudeorchestrator.chatgptbridge.plist"
LABEL="com.claudeorchestrator.chatgptbridge"

chmod +x "$HERE/apply-patch.sh" "$HERE/watch-dropbox.sh"

mkdir -p "$DROPBOX/_applied" "$DROPBOX/_failed" "$DROPBOX/_logs"

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
  <key>StandardOutPath</key><string>$DROPBOX/_logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DROPBOX/_logs/launchd.err.log</string>
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

cat > "$DROPBOX/README.txt" <<'EOF'
ChatGPT → GitHub drop-box
=========================

Drop a patch here and it lands on GitHub automatically (checked every 30s).

Accepted files:  .patch  .diff  .zip  .tar.gz

Naming (this is how the repo is chosen):
    <repo>--<short-slug>.patch
e.g. tomorrow--fix-login-redirect.patch
     claude-orchestrator--add-retry.patch

Known repos: claude-orchestrator, tomorrow, apparently, smarter, illuminati, vigil

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
