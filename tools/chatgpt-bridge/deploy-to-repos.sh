#!/bin/bash
# deploy-to-repos.sh — install the ChatGPT handoff protocol into every repo.
#
# Puts CHATGPT.md + .github/workflows/chatgpt-patch.yml in each repo and pushes
# a branch + PR. Idempotent: re-running updates the files in place.
#
#   ./deploy-to-repos.sh            # PR per repo (default)
#   ./deploy-to-repos.sh --direct   # commit straight to the default branch
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIRECT=0
[ "${1:-}" = "--direct" ] && DIRECT=1

# Fail before touching any repo if the workflow YAML is malformed. GitHub reports a
# bad workflow only as "workflow file issue" after the fact, so gate it here.
python3 - "$HERE/chatgpt-patch.workflow.yml" <<'PY' || exit 1
import sys, yaml
p = sys.argv[1]
try:
    d = yaml.safe_load(open(p))
except yaml.YAMLError as e:
    m = getattr(e, 'problem_mark', None)
    loc = f" (line {m.line+1}, col {m.column+1})" if m else ""
    print(f"ERROR: {p} is not valid YAML: {getattr(e,'problem',e)}{loc}", file=sys.stderr)
    sys.exit(1)
trig = d.get(True, d.get('on'))            # YAML 1.1 parses bare `on:` as True
if not isinstance(trig, dict) or 'workflow_dispatch' not in trig:
    print("ERROR: workflow is missing a workflow_dispatch trigger", file=sys.stderr)
    sys.exit(1)
print("workflow YAML OK")
PY

REPOS=(
  "$HOME/Documents/beethoven/claude-orchestrator"
  "$HOME/Documents/tomorrow/tomorrow"
  "$HOME/Documents/apparently"
  "$HOME/Documents/smarter"
  "$HOME/Documents/illuminati"
  "$HOME/Documents/vigil"
)

for ROOT in "${REPOS[@]}"; do
  NAME="$(basename "$ROOT")"
  echo "=== $NAME"
  [ -d "$ROOT/.git" ] || { echo "  skip (not a git checkout)"; continue; }

  DEF="$(git -C "$ROOT" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
  [ -n "$DEF" ] || DEF="$(git -C "$ROOT" remote show origin 2>/dev/null | awk '/HEAD branch/{print $NF}')"
  [ -n "$DEF" ] || { echo "  skip (cannot resolve default branch)"; continue; }

  git -C "$ROOT" fetch -q origin "$DEF" || { echo "  skip (fetch failed)"; continue; }
  # A previously-merged branch that was deleted on the remote leaves a stale tracking
  # ref, and --force-with-lease then rejects the push as "stale info". Prune all refs
  # (a pruning fetch scoped to one refspec does not clear it).
  git -C "$ROOT" remote prune origin >/dev/null 2>&1

  BR="chore/chatgpt-bridge-protocol"
  WT="${ROOT}-wt/chatgpt-bridge-protocol"
  rm -rf "$WT"; git -C "$ROOT" worktree prune 2>/dev/null
  mkdir -p "$(dirname "$WT")"
  git -C "$ROOT" worktree add -B "$BR" "$WT" "origin/$DEF" -q || { echo "  skip (worktree failed)"; continue; }

  git -C "$WT" config user.name "kalepasch1"
  git -C "$WT" config user.email "kalepasch@gmail.com"

  mkdir -p "$WT/.github/workflows"
  cp "$HERE/chatgpt-patch.workflow.yml" "$WT/.github/workflows/chatgpt-patch.yml"
  sed "s/REPO_NAME_HERE/$NAME/g" "$HERE/CHATGPT.template.md" > "$WT/CHATGPT.md"

  # cross-reference from the repo's agent instructions, once
  for f in AGENTS.md CLAUDE.md; do
    [ -f "$WT/$f" ] || continue
    grep -q 'CHATGPT.md' "$WT/$f" && continue
    printf '\n## No-network agent sessions (ChatGPT sandbox)\n\nChatGPT'"'"'s code sandbox has no outbound network — `git push` and DNS always fail\nthere. Do not debug it. Emit a patch instead: see [CHATGPT.md](./CHATGPT.md).\n' >> "$WT/$f"
    echo "  cross-referenced $f"
  done

  git -C "$WT" add -A
  if git -C "$WT" diff --cached --quiet; then
    echo "  already up to date"
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
    continue
  fi

  git -C "$WT" commit -q -m "chore: add ChatGPT no-network handoff protocol

Sandbox sessions cannot reach github.com. CHATGPT.md tells the agent to emit a
patch instead of debugging DNS; chatgpt-patch.yml applies one from the browser."

  if [ "$DIRECT" -eq 1 ]; then
    git -C "$WT" push -q origin "HEAD:$DEF" && echo "  pushed to $DEF"
  else
    git -C "$WT" push -q -u origin "$BR" --force-with-lease && echo "  pushed $BR"
    if command -v gh >/dev/null; then
      URL="$(cd "$WT" && gh pr create --fill --base "$DEF" --head "$BR" 2>&1 | grep -Eo 'https://github.com/[^ ]+' | head -1)"
      [ -n "$URL" ] && echo "  PR: $URL" || echo "  (PR already open)"
    fi
  fi

  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
  git -C "$ROOT" worktree prune 2>/dev/null
done

echo "done."
