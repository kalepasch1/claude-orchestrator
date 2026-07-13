#!/usr/bin/env bash
set -u
REPO_ROOT="$(pwd)"
CC="$REPO_ROOT/runner/claude_cli.py"
RP="$REPO_ROOT/runner/runner.py"
KA="$REPO_ROOT/runner/keepalive.sh"
if [[ ! -f "$CC" || ! -f "$RP" || ! -f "$KA" ]]; then
  echo "ERROR: run from repo root (missing runner/*.py or keepalive.sh). cwd=$REPO_ROOT" >&2; exit 2
fi
RESULTS="$(mktemp)"; trap 'rm -f "$RESULTS"' EXIT
python3 - "$CC" "$RESULTS" <<'PYEOF'
import sys, io
path, results = sys.argv[1], sys.argv[2]
def emit(s, m):
    print(f"[claude_cli.py] {s} — {m}")
    open(results,"a").write(f"claude_cli.py|{s}\n")
src = io.open(path, encoding="utf-8").read()
if "WEDGEFIX-A-SDK-TIMEOUT" in src: emit("SKIP","already applied"); sys.exit(0)
ANCHOR = ("    loop = asyncio.new_event_loop()\n    try:\n        return loop.run_until_complete(\n"
          "            _run_agent_sdk_async(prompt, model, cwd, runenv, project, max_turns, timeout)\n"
          "        )\n    finally:\n        loop.close()\n")
if src.count(ANCHOR)!=1: emit("FAIL",f"anchor x{src.count(ANCHOR)} — no change"); sys.exit(0)
NEW = ("    # WEDGEFIX-A-SDK-TIMEOUT\n    loop = asyncio.new_event_loop()\n    try:\n"
       "        _coro = _run_agent_sdk_async(prompt, model, cwd, runenv, project, max_turns, timeout)\n"
       "        if timeout:\n            _coro = asyncio.wait_for(_coro, timeout=timeout)\n"
       "        return loop.run_until_complete(_coro)\n"
       "    except asyncio.TimeoutError:\n"
       "        raise subprocess.TimeoutExpired(cmd=\"claude-agent-sdk\", timeout=timeout)\n"
       "    finally:\n        loop.close()\n")
io.open(path+".bak.wedgefix","w",encoding="utf-8").write(src)
io.open(path,"w",encoding="utf-8").write(src.replace(ANCHOR,NEW,1))
emit("PASS","SDK call bounded by asyncio.wait_for")
PYEOF
python3 - "$RP" "$RESULTS" <<'PYEOF'
import sys, io
path, results = sys.argv[1], sys.argv[2]
def emit(s, m):
    print(f"[runner.py] {s} — {m}")
    open(results,"a").write(f"runner.py|{s}\n")
src = io.open(path, encoding="utf-8").read()
if "WEDGEFIX-B-PROGRESS" in src: emit("SKIP","already applied"); sys.exit(0)
A_DEF="def _run_task_safe(t):"
A_CLAIM="                        t = db.claim_task(RUNNER_ID)\n"
A_FIN="        run_task(t)\n"
miss=[n for n,a in (("_run_task_safe",A_DEF),("claim_task",A_CLAIM),("run_task",A_FIN)) if src.count(a)!=1]
if miss: emit("FAIL","missing/ambiguous: "+",".join(miss)+" — no change"); sys.exit(0)
HELPER=('def _touch_progress():\n    # WEDGEFIX-B-PROGRESS\n    try:\n'
        '        _pf = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", "."), "runner.progress")\n'
        '        open(_pf, "a").close()\n        os.utime(_pf, None)\n    except Exception:\n        pass\n\n\n')
new=src.replace(A_DEF,HELPER+A_DEF,1)
new=new.replace(A_CLAIM,A_CLAIM+"                        _touch_progress()  # WEDGEFIX-B-PROGRESS\n",1)
new=new.replace(A_FIN,A_FIN+"        _touch_progress()  # WEDGEFIX-B-PROGRESS\n",1)
io.open(path+".bak.wedgefix","w",encoding="utf-8").write(src)
io.open(path,"w",encoding="utf-8").write(new)
emit("PASS","added _touch_progress() + claim/finish touches")
PYEOF
python3 - "$KA" "$RESULTS" <<'PYEOF'
import sys, io
path, results = sys.argv[1], sys.argv[2]
def emit(s, m):
    print(f"[keepalive.sh] {s} — {m}")
    open(results,"a").write(f"keepalive.sh|{s}\n")
src = io.open(path, encoding="utf-8").read()
if "WEDGEFIX-B-WATCHDOG" in src: emit("SKIP","already applied"); sys.exit(0)
ANCHOR='  ps -p "$pid" >/dev/null 2>&1\n}\n'
if src.count(ANCHOR)!=1: emit("FAIL",f"anchor x{src.count(ANCHOR)} — no change"); sys.exit(0)
NEW=('  if ! ps -p "$pid" >/dev/null 2>&1; then\n    return 1\n  fi\n'
     '  # WEDGEFIX-B-WATCHDOG\n  prog="$CLAUDE_ORCH_HOME/runner.progress"\n'
     '  stall="${ORCH_RUNNER_STALL_SECONDS:-1800}"\n  if [[ -f "$prog" ]]; then\n'
     '    now="$(date +%s)"\n    mtime="$(stat -f %m "$prog" 2>/dev/null || stat -c %Y "$prog" 2>/dev/null)"\n'
     '    if [[ -n "$mtime" ]] && (( now - mtime > stall )); then\n'
     '      echo "[keepalive] runner $pid wedged: no progress $(( now - mtime ))s (>${stall}s) — restarting $(date)" >> "$RUNNER_LOG"\n'
     '      kill -9 "$pid" 2>/dev/null\n      rm -f "$LOCK_FILE"\n      return 1\n    fi\n  fi\n  return 0\n}\n')
io.open(path+".bak.wedgefix","w",encoding="utf-8").write(src)
io.open(path,"w",encoding="utf-8").write(src.replace(ANCHOR,NEW,1))
emit("PASS","added progress-staleness watchdog")
PYEOF
echo; echo "==== WEDGEFIX SUMMARY ===="
fail=0
for f in claude_cli.py runner.py keepalive.sh; do
  st="$(grep "^${f}|" "$RESULTS" | tail -n1 | cut -d'|' -f2)"; [[ -z "$st" ]] && st="FAIL(no-result)"
  printf '  %-14s %s\n' "$f" "$st"; [[ "$st" == FAIL* ]] && fail=1
done
echo "=========================="
[[ "$fail" -ne 0 ]] && { echo "FAILED — files left untouched"; exit 1; }
echo "OK. Now syntax-check + deploy."
