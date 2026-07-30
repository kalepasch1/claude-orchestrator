#!/usr/bin/env bash
# Re-drop the 5 overhaul prompts so the FIXED planner shards them into proper DAGs.
# Run AFTER the runner has restarted with the planner fix loaded:
#   bash ~/Documents/beethoven/claude-orchestrator/redrop_prompts.sh
set -euo pipefail
cd "$(dirname "$0")"

for f in apparently-vigil-merge illuminati-overlay-and-trust pareto-luxury-ecp-exchange \
         smarter-embed-and-coordination tomorrow-selfservice-insights-ecp; do
  src="$(ls -1 intake/processed/*dropbox-PROMPT-"$f".md 2>/dev/null | head -1)"
  if [ -n "${src:-}" ]; then
    cp "$src" "PROMPT-$f.md" && echo "re-dropped PROMPT-$f.md"
  else
    echo "WARN: no processed source found for $f (skipping)"
  fi
done
echo "done — the intake watcher will ingest these within a cycle and shard each into ~10-17 tasks."
