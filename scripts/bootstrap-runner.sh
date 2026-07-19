#!/usr/bin/env bash
# bootstrap-runner.sh: Automate runner setup from SETUP-MAC2.md
#
# Idempotent bootstrap that prepares a host to run the Claude Orchestrator fleet runner:
# - Validates Supabase credentials
# - Clones/updates fleet repos
# - Manages runner/.env (regenerates if stale)
# - Installs dependencies (brew/apt-based)
# - Generates launchd (macOS) or systemd (Linux) unit
# - Registers host in runner_heartbeats
# - Runs smoke test
#
# Usage: SUPABASE_URL=... SUPABASE_SERVICE_KEY=... ./scripts/bootstrap-runner.sh
#
# Environment variables (precedence):
#  - SUPABASE_URL, SUPABASE_SERVICE_KEY (required; prompts if missing)
#  - RUNNER_REPO_LIST (space-separated; optional; queries DB if unset)
#  - INSTALL_OLLAMA (true/false; default: false)
#  - TARGET_PLATFORM (darwin/linux; auto-detect if unset)
#  - DRY_RUN (true/false; default: false; skip filesystem/service writes)
set -uo pipefail

# ── Initialization ──────────────────────────────────────────────────────────
SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_SERVICE_KEY="${SUPABASE_SERVICE_KEY:-}"
RUNNER_REPO_LIST="${RUNNER_REPO_LIST:-}"
INSTALL_OLLAMA="${INSTALL_OLLAMA:-false}"
TARGET_PLATFORM="${TARGET_PLATFORM:-}"
DRY_RUN="${DRY_RUN:-false}"

DOCS_DIR="${HOME}/Documents"
RUNNER_DIR="${DOCS_DIR}/beethoven/claude-orchestrator/runner"
RUNNER_REPO_DIR="${DOCS_DIR}/beethoven/claude-orchestrator"

# Track success; non-critical failures don't halt bootstrap
BOOTSTRAP_SUCCESS=0

# Logging helpers
log() { echo "[bootstrap] $*" >&2; }
warn() { echo "[bootstrap:warn] $*" >&2; }
error() { echo "[bootstrap:error] $*" >&2; exit 1; }
info() { echo "$*" >&2; }

# ── Platform Detection ──────────────────────────────────────────────────────
detect_platform() {
  if [[ -n "$TARGET_PLATFORM" ]]; then
    echo "$TARGET_PLATFORM"
  else
    uname -s | tr '[:upper:]' '[:lower:]'
  fi
}

PLATFORM=$(detect_platform)
case "$PLATFORM" in
  darwin|linux) log "Platform: $PLATFORM" ;;
  *)
    error "Unsupported platform: $PLATFORM (uname -s output: $(uname -s))"
    ;;
esac

# ── Secret Handling (non-interactive: fail; interactive: prompt) ─────────────
prompt_for_secret() {
  local name="$1"
  local var_name="$2"
  local current_value="${!var_name:-}"

  if [[ -n "$current_value" ]]; then
    return 0
  fi

  # Non-interactive check: if stdout is not a TTY, fail
  if [[ ! -t 0 ]]; then
    error "Non-interactive mode: required secret '$name' not set via $var_name environment variable"
  fi

  # Interactive prompt (read -s prevents terminal echo)
  echo -n "Enter $name (will not echo): " >&2
  read -rs secret_value
  echo >&2
  eval "$var_name='$secret_value'"
}

log "Checking Supabase credentials..."
prompt_for_secret "Supabase URL" "SUPABASE_URL"
prompt_for_secret "Supabase Service Key" "SUPABASE_SERVICE_KEY"

if [[ -z "$SUPABASE_URL" ]] || [[ -z "$SUPABASE_SERVICE_KEY" ]]; then
  error "Missing required environment variables: SUPABASE_URL, SUPABASE_SERVICE_KEY"
fi

# ── Validate Supabase Credentials ───────────────────────────────────────────
log "Validating Supabase credentials..."
validate_supabase() {
  local response
  response=$(curl -s --max-time 5 -X GET \
    "${SUPABASE_URL}/rest/v1/runner_heartbeats?select=id&limit=1" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
    -H "Content-Type: application/json" \
    2>&1) || return 1

  # Supabase returns [] on success; check for valid JSON array response
  if echo "$response" | grep -qE '^\[|"id"'; then
    return 0
  fi
  return 1
}

if ! validate_supabase; then
  error "Failed to validate Supabase credentials. Check SUPABASE_URL and SUPABASE_SERVICE_KEY."
fi
log "✓ Supabase credentials valid"

# ── Repository Cloning/Updating ─────────────────────────────────────────────
log "Managing repositories..."

clone_or_update_repo() {
  local repo_name="$1"
  local repo_url="$2"
  local repo_path="${DOCS_DIR}/${repo_name}"

  if [[ -d "$repo_path/.git" ]]; then
    log "Updating $repo_name at $repo_path"
    cd "$repo_path"
    if ! git pull --ff-only origin master 2>/dev/null; then
      warn "Failed to pull $repo_name; continuing with local state"
    fi
  else
    log "Cloning $repo_name to $repo_path"
    mkdir -p "$(dirname "$repo_path")"
    if ! git clone "$repo_url" "$repo_path" 2>/dev/null; then
      warn "Failed to clone $repo_name; skipping"
      return 1
    fi
  fi
  return 0
}

# Fetch repo list from RUNNER_REPO_LIST or Supabase projects table
if [[ -n "$RUNNER_REPO_LIST" ]]; then
  log "Using RUNNER_REPO_LIST: $RUNNER_REPO_LIST"
  for repo in $RUNNER_REPO_LIST; do
    clone_or_update_repo "$repo" "https://github.com/anthropics/${repo}.git" || true
  done
else
  log "Fetching repo list from Supabase projects table..."
  projects=$(curl -s --max-time 10 -X GET \
    "${SUPABASE_URL}/rest/v1/projects?select=repo_name" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
    -H "Content-Type: application/json" 2>/dev/null | \
    grep -o '"repo_name":"[^"]*' | cut -d'"' -f4 | sort -u) || projects=""

  if [[ -z "$projects" ]]; then
    log "No projects found in DB; skipping repo cloning"
  else
    for repo in $projects; do
      clone_or_update_repo "$repo" "https://github.com/anthropics/${repo}.git" || true
    done
  fi
fi

# ── Environment File Management ─────────────────────────────────────────────
log "Managing runner/.env..."

manage_env() {
  local env_path="${RUNNER_DIR}/.env"
  local env_example="${RUNNER_DIR}/.env.example"

  # If both missing, create minimal template inline
  if [[ ! -f "$env_example" ]] && [[ ! -f "$env_path" ]]; then
    log "Generating minimal .env template (no .env.example found)"
    if [[ "$DRY_RUN" != "true" ]]; then
      mkdir -p "$RUNNER_DIR"
      cat > "$env_path" <<EOF
SUPABASE_URL=$SUPABASE_URL
SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE_KEY
MAX_PARALLEL=2
POLL_SECONDS=5
EOF
      chmod 600 "$env_path"
    fi
    return
  fi

  # If .env missing or differs from .env.example, regenerate
  if [[ ! -f "$env_path" ]]; then
    log "Regenerating .env from .env.example"
    if [[ "$DRY_RUN" != "true" ]]; then
      if [[ -f "$env_example" ]]; then
        cp "$env_example" "$env_path"
        chmod 600 "$env_path"
        # Update secrets in .env
        if [[ "$PLATFORM" == "darwin" ]]; then
          sed -i '' "s|^SUPABASE_URL=.*|SUPABASE_URL=$SUPABASE_URL|" "$env_path"
          sed -i '' "s|^SUPABASE_SERVICE_KEY=.*|SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE_KEY|" "$env_path"
        else
          sed -i "s|^SUPABASE_URL=.*|SUPABASE_URL=$SUPABASE_URL|" "$env_path"
          sed -i "s|^SUPABASE_SERVICE_KEY=.*|SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE_KEY|" "$env_path"
        fi
      fi
    fi
  fi
}

manage_env

# ── Dependency Installation ────────────────────────────────────────────────
log "Installing dependencies for $PLATFORM..."

install_deps() {
  if [[ "$PLATFORM" == "darwin" ]]; then
    # macOS: use Homebrew
    if ! command -v brew &> /dev/null; then
      log "Installing Homebrew..."
      if [[ "$DRY_RUN" != "true" ]]; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || \
          warn "Homebrew install failed; ensure it's installed manually"
      fi
    fi

    if command -v brew &> /dev/null; then
      log "Installing Python via Homebrew..."
      if [[ "$DRY_RUN" != "true" ]]; then
        brew install python@3.11 2>/dev/null || warn "Failed to install Python@3.11"
      fi
    fi
  else
    # Linux: use apt
    if ! command -v apt-get &> /dev/null; then
      error "apt-get not found; this script requires Debian/Ubuntu-based systems"
    fi

    log "Installing Python via apt..."
    if [[ "$DRY_RUN" != "true" ]]; then
      sudo apt-get update >/dev/null 2>&1 || warn "apt-get update failed"
      sudo apt-get install -y python3 python3-pip python3-venv >/dev/null 2>&1 || \
        warn "Failed to install Python packages"
    fi
  fi

  # Optional: Ollama
  if [[ "$INSTALL_OLLAMA" == "true" ]]; then
    log "Installing Ollama..."
    if [[ "$DRY_RUN" != "true" ]]; then
      if [[ "$PLATFORM" == "darwin" ]]; then
        brew install ollama 2>/dev/null || warn "Failed to install Ollama via brew"
      else
        curl -fsSL https://ollama.ai/install.sh 2>/dev/null | sh 2>/dev/null || \
          warn "Failed to install Ollama; install manually"
      fi
    fi
  fi
}

install_deps

# ── Service Unit Installation (launchd/systemd) ────────────────────────────
log "Installing service unit..."

install_service() {
  if [[ "$PLATFORM" == "darwin" ]]; then
    install_launchd
  else
    install_systemd
  fi
}

install_launchd() {
  local plist_path="/Library/LaunchDaemons/com.heretomorrow.orchestrator.plist"
  local plist_tmp="/tmp/com.heretomorrow.orchestrator.plist"

  log "Generating launchd plist at $plist_path"

  cat > "$plist_tmp" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.heretomorrow.orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>__RUNNER_DIR__/runner.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>__RUNNER_DIR__</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>__HOME__/Library/Logs/orchestrator.log</string>
  <key>StandardErrorPath</key>
  <string>__HOME__/Library/Logs/orchestrator.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>__HOME__</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
EOF

  # Substitute paths
  if [[ "$PLATFORM" == "darwin" ]]; then
    sed -i '' "s|__RUNNER_DIR__|$RUNNER_DIR|g" "$plist_tmp"
    sed -i '' "s|__HOME__|$HOME|g" "$plist_tmp"
  else
    sed -i "s|__RUNNER_DIR__|$RUNNER_DIR|g" "$plist_tmp"
    sed -i "s|__HOME__|$HOME|g" "$plist_tmp"
  fi

  if [[ "$DRY_RUN" != "true" ]]; then
    sudo mv "$plist_tmp" "$plist_path" || error "Failed to install launchd plist"
    sudo chown root:wheel "$plist_path" 2>/dev/null || warn "Failed to set launchd ownership"
    sudo chmod 644 "$plist_path" 2>/dev/null || warn "Failed to set launchd permissions"
    log "✓ Launchd plist installed"
  fi
}

install_systemd() {
  local systemd_path="/etc/systemd/system/orchestrator.service"
  local systemd_tmp="/tmp/orchestrator.service"

  log "Generating systemd unit at $systemd_path"

  cat > "$systemd_tmp" <<EOF
[Unit]
Description=Claude Orchestrator Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$RUNNER_DIR
ExecStart=/usr/bin/python3 $RUNNER_DIR/runner.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="HOME=$HOME"

[Install]
WantedBy=multi-user.target
EOF

  if [[ "$DRY_RUN" != "true" ]]; then
    sudo mv "$systemd_tmp" "$systemd_path" || error "Failed to install systemd unit"
    sudo chmod 644 "$systemd_path" || warn "Failed to set systemd permissions"

    # Validate systemd unit
    if command -v systemd-analyze &> /dev/null; then
      if ! sudo systemd-analyze verify "$systemd_path" >/dev/null 2>&1; then
        warn "systemd unit validation failed; check $systemd_path"
      else
        log "✓ systemd unit validated"
      fi
    fi

    # Reload systemd
    sudo systemctl daemon-reload >/dev/null 2>&1 || warn "Failed to reload systemd"
  fi
}

install_service

# ── Host Registration in Database ──────────────────────────────────────────
log "Registering host in database..."

register_host() {
  local hostname=$(hostname)
  local timestamp=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

  if [[ "$DRY_RUN" == "true" ]]; then
    log "[DRY_RUN] Would register host: $hostname"
    return 0
  fi

  local response=$(curl -s --max-time 5 -X POST \
    "${SUPABASE_URL}/rest/v1/runner_heartbeats" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"hostname\": \"$hostname\", \"status\": \"initialized\", \"last_heartbeat\": \"$timestamp\"}" \
    2>&1) || {
    warn "Failed to register host (network error)"
    return 1
  }

  # Check for valid response
  if echo "$response" | grep -qE '^\[|"id"'; then
    log "✓ Host registered: $hostname"
    return 0
  else
    warn "Host registration failed: $response"
    return 1
  fi
}

register_host || BOOTSTRAP_SUCCESS=1

# ── Smoke Test ──────────────────────────────────────────────────────────────
log "Running smoke test..."

run_smoke_test() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log "[DRY_RUN] Would run smoke test"
    return 0
  fi

  if [[ ! -f "$RUNNER_DIR/runner.py" ]]; then
    warn "runner.py not found; skipping smoke test"
    return 1
  fi

  # Simple import check instead of full cycle
  cd "$RUNNER_DIR" || return 1
  if python3 -c "import runner; print('Smoke test passed')" 2>/dev/null; then
    log "✓ Smoke test passed"
    return 0
  else
    warn "Smoke test failed (runner import); continuing anyway"
    return 1
  fi
}

run_smoke_test || BOOTSTRAP_SUCCESS=1

# ── Completion ──────────────────────────────────────────────────────────────
log ""
if [[ "$BOOTSTRAP_SUCCESS" -eq 0 ]]; then
  log "✓ Bootstrap completed successfully"
  log ""
  log "Next steps:"
  log "  1. Verify heartbeat: (cd $RUNNER_DIR && python3 fleet.py)"
  log "  2. Check status: (cd $RUNNER_DIR && python3 fleet_doctor.py --brief)"
  if [[ "$PLATFORM" == "darwin" ]]; then
    log "  3. Enable launchd: launchctl load /Library/LaunchDaemons/com.heretomorrow.orchestrator.plist"
  else
    log "  3. Enable systemd: sudo systemctl enable --now orchestrator.service"
  fi
  exit 0
else
  log "⚠ Bootstrap completed with warnings (non-critical failures; check above)"
  exit 0
fi
