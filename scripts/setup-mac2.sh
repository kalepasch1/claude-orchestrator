#!/usr/bin/env bash
# One-shot setup for a runner Mac (built for Mac 2 / Mandy's machine): pulls the latest orchestrator
# code, sizes the runner to this Mac's RAM (cures the "idle / claims nothing" issue), installs the
# free local coder (aider + Ollama qwen2.5-coder), registers the multi-coder pool, and restarts.
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

echo "==> 1/5  pull the latest orchestrator code"
git pull --ff-only || echo "   (git pull skipped/failed — continuing with local code)"

echo "==> 2/5  size the runner to THIS Mac's RAM (fixes idle/claims-nothing)"
TOTAL_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8000000000) / 1000000000 ))
LANES=$(( (TOTAL_GB - 4) / 3 )); [ "$LANES" -lt 1 ] && LANES=1
echo "   total RAM ${TOTAL_GB}GB -> $LANES lanes"
setenv() { local k="${1%%=*}"; if grep -q "^$k=" "$ENVF"; then sed -i '' "s|^$k=.*|$1|" "$ENVF"; else echo "$1" >> "$ENVF"; fi; }
setenv "MAX_PARALLEL=$LANES"; setenv "MAX_PARALLEL_CEILING=$LANES"
setenv "PER_TASK_GB=3.0"; setenv "RAM_FLOOR_GB=4.0"

echo "==> 3/5  install the free local coder (aider + Ollama qwen2.5-coder)"
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
  ollama pull "${OLLAMA_CODE_MODEL:-qwen2.5-coder}" || echo "   (pull failed — run: ollama pull qwen2.5-coder)"
fi

echo "==> 4/5  register the coder pool (free local + any paid models whose keys are present)"
CODERS=""
add() { CODERS="${CODERS:+$CODERS,}$1"; }
haskey() { [ -n "${!1:-}" ] || grep -q "^$1=" "$ENVF" 2>/dev/null; }
if command -v aider >/dev/null 2>&1 && command -v ollama >/dev/null 2>&1; then
  add '{"name":"ollama-qwen","cmd":"aider --model ollama/'"${OLLAMA_CODE_MODEL:-qwen2.5-coder}"' --yes --no-auto-commit --message {prompt}","cost":0,"cap":5}'
fi
if command -v aider >/dev/null 2>&1; then
  haskey DEEPSEEK_API_KEY && add '{"name":"deepseek","cmd":"aider --model deepseek/deepseek-chat --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
  haskey GEMINI_API_KEY   && add '{"name":"gemini","cmd":"aider --model gemini/gemini-2.0-flash --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
  haskey OPENAI_API_KEY   && add '{"name":"gpt","cmd":"aider --model openai/gpt-4o-mini --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}'
fi
if [ -n "$CODERS" ]; then
  grep -v '^ORCH_EXTRA_CODERS=' "$ENVF" > "$ENVF.tmp" && mv "$ENVF.tmp" "$ENVF"
  printf "ORCH_EXTRA_CODERS='[%s]'\n" "$CODERS" >> "$ENVF"
  grep -q '^ORCH_EASY_OFFLOAD_SHARE=' "$ENVF" || echo 'ORCH_EASY_OFFLOAD_SHARE=0.6' >> "$ENVF"
  echo "   pool: [$CODERS]"
else
  echo "   (no extra coders configured yet — aider/ollama not ready; re-run after installing)"
fi

echo "==> 5/5  restart the runner"
pkill -9 -f keepalive.sh 2>/dev/null || true
pkill -9 -f "runner.py" 2>/dev/null || true
sleep 3
rm -f "$REPO/.runtime/runner.lock" 2>/dev/null || true
( cd "$REPO/runner" && nohup bash keepalive.sh >/dev/null 2>&1 & )
sleep 6
echo ""
echo "==> DONE. Verify:"
echo "    pgrep -fl 'keepalive.sh|runner.py'      # runner should be up"
echo "    (cd \"$REPO/runner\" && python3 agentic_coders.py)   # should list claude, codex, ollama-qwen, ..."
