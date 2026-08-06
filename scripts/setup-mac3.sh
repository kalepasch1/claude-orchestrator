#!/usr/bin/env bash
# One-shot join for a CLOUD/HOSTED-INFERENCE-ONLY runner Mac (built for Mac 3).
#
# Difference from setup-mac2.sh: Mac 3 runs Claude Cowork and hosted models ONLY. It installs
# NO Ollama and NO aider, and it pins ORCH_DISABLE_LOCAL_MODELS=1 so nothing can schedule a
# multi-GB local model onto it. Mac 1 keeps its local models; this box contributes RAM + lanes
# for agent work that routes to hosted inference.
#
# Why adding a host helps at all: the governor throttles lanes off FREE RAM per machine, and
# Mac 1 is memory-bound (fseventsd alone was 17GB on a 48GB box), so it runs far under its
# 40-lane ceiling. A third host adds lanes that are not competing for Mac 1's RAM.
#
# Safe + idempotent.  Run from inside the repo:   bash scripts/setup-mac3.sh
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "${REPO:-}" ] && REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "!! run this from inside the claude-orchestrator repo"; exit 1; }
ENVF="runner/.env"
echo "==> repo: $REPO"
echo "==> host: $(hostname) / $(scutil --get ComputerName 2>/dev/null)"

if [ ! -f "$ENVF" ]; then
  echo "!! $ENVF is missing. Copy it from Mac 1 first (it holds SUPABASE_URL +"
  echo "   SUPABASE_SERVICE_KEY + ORCH_SUPABASE_FALLBACK_URLS). Without it this host"
  echo "   cannot reach the control plane and will look silently idle."
  exit 1
fi

setenv() { local k="${1%%=*}"; if grep -q "^$k=" "$ENVF"; then sed -i '' "s|^$k=.*|$1|" "$ENVF"; else echo "$1" >> "$ENVF"; fi; }

echo "==> 1/5  pull the latest orchestrator code"
git pull --ff-only || echo "   (pull skipped — continuing on local code)"

echo "==> 2/5  size lanes to THIS Mac's RAM"
TOTAL_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8000000000) / 1000000000 ))
LANES=$(( (TOTAL_GB - 4) * 2 )); [ "$LANES" -lt 1 ] && LANES=1
echo "   ${TOTAL_GB}GB total -> ceiling $LANES lanes (runtime concurrency still governed live by free RAM)"
setenv "MAX_PARALLEL=$LANES"; setenv "MAX_PARALLEL_CEILING=$LANES"
setenv "PER_TASK_GB=0.5"; setenv "RAM_FLOOR_GB=4.0"
setenv "ORCH_AUTO_PULL=true"; setenv "ORCH_AUTO_PULL_RESTART=true"; setenv "ORCH_AUTO_PULL_MIN=2"
setenv "ORCH_FLEET_TICK_S=30"; setenv "ORCH_KEEPALIVE_STAY_RESIDENT=true"

echo "==> 3/5  HOSTED INFERENCE ONLY — no Ollama, no aider, no local model pulls"
setenv "ORCH_DISABLE_LOCAL_MODELS=1"
# Belt and braces: even if a local backend appears later, never calibrate or canary it here.
setenv "ORCH_DISABLED_JOBS=ollamacal-3600,histmodel-night"
grep -v '^ORCH_EXTRA_CODERS=' "$ENVF" > "$ENVF.tmp" 2>/dev/null && mv "$ENVF.tmp" "$ENVF"
if command -v claude >/dev/null 2>&1; then
  echo "   claude CLI: $(command -v claude)"
else
  echo "   !! claude CLI not on PATH — this host can host lanes but cannot run agent tasks."
  echo "      Install Claude Code on this Mac, then re-run."
fi

echo "==> 4/5  project repos this host can work on"
( cd "$REPO/runner" && set -a && . ./.env && set +a && python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
import db
rows = db.select("projects", {"select": "name,repo_path"}) or []
have = [r for r in rows if r.get("repo_path") and os.path.isdir(r["repo_path"])]
miss = [r for r in rows if not (r.get("repo_path") and os.path.isdir(r["repo_path"]))]
print(f"   present: {len(have)}/{len(rows)}")
for r in miss:
    print(f"   missing: {r['name']:<28} {r.get('repo_path')}")
print("   (a project whose repo is absent is simply skipped on this host — safe, just idle capacity)")
PY
) || echo "   (project check skipped — verify runner/.env reaches Supabase)"

echo "==> 5/5  install the launchd supervisor"
bash "$REPO/scripts/setup-scheduler.sh" || echo "   (needs Full Disk Access for ClaudeRunner.app, then re-run)"
launchctl kickstart -k "gui/$(id -u)/com.claudeorchestrator.runner" 2>/dev/null || true
sleep 8

echo ""
echo "==> DONE. Verify this host joined the fleet:"
echo "    (cd \"$REPO/runner\" && python3 fleet.py)                 # this Mac should appear"
echo "    (cd \"$REPO/runner\" && python3 fleet_doctor.py --brief)"
echo "    grep -E '^(MAX_PARALLEL|ORCH_DISABLE_LOCAL_MODELS)=' \"$ENVF\""
