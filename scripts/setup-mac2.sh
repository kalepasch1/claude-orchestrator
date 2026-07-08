#!/usr/bin/env bash
# One-shot setup for a runner Mac (built for Mac 2): pulls the latest orchestrator code, sizes the
# runner to this Mac's RAM, installs local/cheap coder paths, registers the multi-coder pool, installs
# the same launchd + ClaudeRunner.app supervisor as Mac 1, and enables central fleet control.
#
# Safe + idempotent. Nothing here needs an API key; paid models are only added if their key already
# exists in the environment or runner/.env. Run:  bash scripts/setup-mac2.sh   (from the repo)
set -uo pipefail

# locate the repo no matter where it lives on this machine
REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "${REPO:-}" ] && REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "!! run this from inside the claude-orchestrator repo"; exit 1; }
ENVF="runner/.env"; touch "$ENVF"
echo "==> repo: $REPO"

echo "==> 1/6  pull the latest orchestrator code"
git pull --ff-only || echo "   (git pull skipped/failed — continuing with local code)"

echo "==> 2/6  size the runner to THIS Mac's RAM (fixes idle/claims-nothing)"
TOTAL_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8000000000) / 1000000000 ))
LANES=$(( (TOTAL_GB - 4) / 3 )); [ "$LANES" -lt 1 ] && LANES=1
echo "   total RAM ${TOTAL_GB}GB -> $LANES lanes"
setenv() { local k="${1%%=*}"; if grep -q "^$k=" "$ENVF"; then sed -i '' "s|^$k=.*|$1|" "$ENVF"; else echo "$1" >> "$ENVF"; fi; }
setenv "MAX_PARALLEL=$LANES"; setenv "MAX_PARALLEL_CEILING=$LANES"
setenv "PER_TASK_GB=3.0"; setenv "RAM_FLOOR_GB=4.0"
setenv "ORCH_AUTO_PULL=true"; setenv "ORCH_AUTO_PULL_RESTART=true"; setenv "ORCH_AUTO_PULL_MIN=2"
setenv "ORCH_FLEET_TICK_S=30"; setenv "ORCH_KEEPALIVE_STAY_RESIDENT=true"
setenv "ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS=60"
setenv "ORCH_RECOVERY_JUMP_QUEUE=true"; setenv "ORCH_RELEASE_FIX_JUMP_QUEUE=true"
setenv "ORCH_EVIDENCE_JUMP_QUEUE=true"

echo "==> 3/6  install local/cheap coder tools (aider + Ollama)"
if ! command -v aider >/dev/null 2>&1; then
  brew install pipx 2>/dev/null; command -v pipx >/dev/null 2>&1 && pipx ensurepath 2>/dev/null
  pipx install aider-chat 2>/dev/null \
    || python3 -m pip install --user --break-system-packages aider-chat 2>/dev/null \
    || python3 -m pip install --user aider-chat 2>/dev/null \
    || echo "   (install aider manually: pipx install aider-chat)"
fi
command -v ollama >/dev/null 2>&1 || brew install ollama 2>/dev/null || echo "   (install Ollama: https://ollama.com/download)"
if command -v ollama >/dev/null 2>&1; then
  (ollama serve >/dev/null 2>&1 &) ; sleep 2
  OLLAMA_CODE_MODEL="${OLLAMA_CODE_MODEL:-qwen3-coder:30b}"
  ollama pull "$OLLAMA_CODE_MODEL" || echo "   (pull failed — run: ollama pull $OLLAMA_CODE_MODEL)"
  if [ "${ORCH_PULL_HEAVY_MODELS:-false}" = "true" ]; then
    for m in deepseek-coder-v2:16b codestral:22b gemma3:12b; do
      ollama pull "$m" || echo "   (optional pull failed: $m)"
    done
  fi
fi

echo "==> 4/6  register the coder pool (local + any paid/value models whose keys are present)"
CODERS=""
add() { CODERS="${CODERS:+$CODERS,}$1"; }
haskey() { [ -n "${!1:-}" ] || grep -q "^$1=" "$ENVF" 2>/dev/null; }
if command -v aider >/dev/null 2>&1 && command -v ollama >/dev/null 2>&1; then
  add '{"name":"ollama-qwen3-coder","cmd":"python3 -m aider --model ollama/'"${OLLAMA_CODE_MODEL:-qwen3-coder:30b}"' --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":0,"cap":7}'
  if ollama list 2>/dev/null | grep -q '^deepseek-coder-v2'; then
    add '{"name":"ollama-deepseek-coder-v2","cmd":"python3 -m aider --model ollama/deepseek-coder-v2:16b --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":0,"cap":6}'
  fi
  if ollama list 2>/dev/null | grep -q '^codestral'; then
    add '{"name":"ollama-codestral","cmd":"python3 -m aider --model ollama/codestral:22b --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":0,"cap":6}'
  fi
fi
if command -v aider >/dev/null 2>&1; then
  haskey DEEPSEEK_API_KEY && add '{"name":"deepseek","cmd":"python3 -m aider --model deepseek/deepseek-chat --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
  haskey GEMINI_API_KEY   && add '{"name":"gemini","cmd":"python3 -m aider --model gemini/gemini-2.0-flash --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
  haskey OPENAI_API_KEY   && add '{"name":"gpt","cmd":"python3 -m aider --model openai/gpt-4o-mini --yes-always --no-auto-commits --no-show-model-warnings --no-check-model-accepts-settings --no-browser --no-gui --no-check-update --analytics-disable --no-detect-urls --no-notifications --no-gitignore --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
fi
if [ -n "$CODERS" ]; then
  grep -v '^ORCH_EXTRA_CODERS=' "$ENVF" > "$ENVF.tmp" && mv "$ENVF.tmp" "$ENVF"
  printf "ORCH_EXTRA_CODERS='[%s]'\n" "$CODERS" >> "$ENVF"
  grep -q '^ORCH_EASY_OFFLOAD_SHARE=' "$ENVF" || echo 'ORCH_EASY_OFFLOAD_SHARE=0.6' >> "$ENVF"
  echo "   pool: [$CODERS]"
else
  echo "   (no extra coders configured yet — aider/ollama not ready; re-run after installing)"
fi

echo "==> 5/6  enable central fleet defaults"
( cd "$REPO/runner" && python3 fleetctl.py bootstrap-defaults ) || echo "   (fleet defaults skipped — check Supabase env/schema)"

echo "==> 6/6  install/restart the launchd supervisor"
bash "$REPO/scripts/setup-scheduler.sh" || echo "   (launchd setup needs attention; run scripts/setup-scheduler.sh again after Full Disk Access)"
launchctl kickstart -k "gui/$(id -u)/com.claudeorchestrator.runner" 2>/dev/null || true
sleep 8
echo ""
echo "==> DONE. Verify:"
echo "    (cd \"$REPO/runner\" && python3 fleet_doctor.py --brief)"
echo "    (cd \"$REPO/runner\" && python3 fleet.py)             # should list this Mac once heartbeat lands"
echo "    (cd \"$REPO/runner\" && python3 agentic_coders.py)   # should list claude/codex/ollama/value coders"
