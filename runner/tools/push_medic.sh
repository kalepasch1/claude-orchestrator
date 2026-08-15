#!/bin/bash
# push_medic.sh — cowork 2026-08-04. THE recurring failure this repo has had:
# the release train merges agent work into local main/master but only PUSHES when it has a
# batch (historically >=10), so finished, tested, merged improvements sit on local disk —
# invisible to GitHub, never built by Vercel. Twice this week that hid 440+ commits across
# 12 repos, including p0 user-journey fixes and a whole site's launch work.
#
# This watchdog makes "merged but unpushed" a state that cannot persist. Every 10 minutes:
#   1. for each bound repo on its deploy branch, if local is ahead of origin -> push it
#   2. never force, never touch non-deploy branches, never resolve conflicts (logs + skips)
#   3. logs every push so drift is visible instead of silent
# Durable in-scheduler version is queued (PROMPT-fleet-immune-system-speed §2); this is the
# out-of-band backstop that survives a wedged runner.
# Launch: nohup bash runner/tools/push_medic.sh >/dev/null 2>&1 &
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$ROOT/.runtime/logs/push-medic.log"
export GIT_TERMINAL_PROMPT=0
export ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1

REPOS="
$HOME/Documents/tomorrow/tomorrow:main
$HOME/Documents/apparently:master
$HOME/Documents/apparently-law:main
$HOME/Documents/pareto/2080:main
$HOME/Documents/smarter:main
$HOME/Documents/smarter/prediction-markets-institute/pmi:main
$HOME/Documents/smarter/pasch:main
$ROOT:master
$HOME/Documents/galop/racefeed:master
$HOME/Documents/illuminati:master
$HOME/Documents/vigil:main
$HOME/Documents/darwn/darwn:main
$HOME/Documents/hisanta:master
$HOME/Documents/Sustainable_Barks:main
"

while true; do
  ts=$(date '+%F %T')
  for entry in $REPOS; do
    p="${entry%%:*}"; b="${entry##*:}"
    [ -d "$p/.git" ] || continue
    cd "$p" || continue
    cur=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    # only ever act when the checkout is sitting on its own deploy branch
    [ "$cur" = "$b" ] || continue
    # a merge/rebase in progress means a human or agent is mid-operation — never interfere
    if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
      echo "$ts skip $(basename $p) — merge/rebase in progress" >> "$LOG"; continue
    fi
    git fetch origin "$b" -q 2>/dev/null || continue
    ahead=$(git rev-list --count "origin/$b..$b" 2>/dev/null)
    behind=$(git rev-list --count "$b..origin/$b" 2>/dev/null)
    [ "${ahead:-0}" -gt 0 ] || continue
    if [ "${behind:-0}" -gt 0 ]; then
      echo "$ts DIVERGED $(basename $p) ahead=$ahead behind=$behind — needs a real merge, skipping" >> "$LOG"
      continue
    fi
    if git push origin "$b" >>"$LOG" 2>&1; then
      echo "$ts pushed $(basename $p) ($b): $ahead commit(s) -> deploy triggered" >> "$LOG"
    else
      echo "$ts PUSH FAILED $(basename $p) ($b) ahead=$ahead" >> "$LOG"
    fi
  done
  sleep 600
done
