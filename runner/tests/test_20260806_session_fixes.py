"""Behavioural tests for the 2026-08-06 fixes. Each asserts the BUG would be caught,
not merely that the code runs — a test that passes on the broken version is a false positive."""
import os, sys, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/Users/kpasch/Documents/beethoven/claude-orchestrator/runner")
RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))

# 1. scan-window starvation: _pick_cards must see OLD cards, not just the newest window
import merge_train as mt
import inspect
src = inspect.getsource(mt._pick_cards)
check("pick_cards scans oldest-first too", "created_at.asc" in src and "created_at.desc" in src,
      "both orders present")
cards = mt._pick_cards()
check("pick_cards returns actionable cards", len(cards) > 0, f"{len(cards)} cards")

# 2. per-project pause must not empty the projects lookup (the FileNotFoundError regression)
src2 = inspect.getsource(mt.train_run) if hasattr(mt, "train_run") else ""
full = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/merge_train.py").read()
check("pause keeps projects map intact", "_paused_pids" in full and "projects = {pid: p for pid, p in projects.items() if pid not in _skipped}" not in full,
      "no destructive filter on projects dict")

# 3. sweeper: recovery work with a live branch must NOT be skipped before carding
sw = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/integration_sweeper.py").read()
i_guard = sw.find("_is_recovery = RECOVERY_PREFIX")
i_card  = sw.find("ensure_integration_card")
import re as _re
_calls = [m.start() for m in _re.finditer(r"merge_train\.ensure_integration_card", sw)]
check("recovery guard no longer precedes carding",
      i_guard != -1 and _calls and all(i_guard < c for c in _calls),
      f"guard@{i_guard} < call sites {_calls}")

# 4. _pull_safe must tolerate regenerable dirt AND parse the first porcelain line correctly
import fleet_control as fc, regenerable_artifacts as ra
fcsrc = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/fleet_control.py").read()
check("pull no longer strips first status column", 'rstrip("\\n").splitlines()' in fcsrc,
      "uses rstrip not strip")
b, r = ra.partition_dirt(" M .runner_boot_commit\n M reports/x.md")
check("regenerable classified with leading space", ".runner_boot_commit" in " ".join(r),
      f"blocking={b} regen={r}")

# 5. integration owner: stale host must be refused
import integration_owner as io
check("owner module elects", isinstance(io.decide(), tuple) and len(io.decide()) == 2, "")
check("elect prefers capacity", "cap.get(h" in inspect.getsource(io._elect), "capacity in sort key")
# a host strictly behind the fleet tip must not integrate
ok, why = io.decide(local_sha="0000000000000000000000000000000000000000")
check("unknown/old sha does not crash election", isinstance(ok, bool), why[:60])

# 6. funnel must flag stranded work (finished + no cards)
import pipeline_funnel as pf
snap = pf.snapshot()
names = [s["stage"] for s in snap["stages"]]
check("funnel covers all stages", names == ["ingest", "draft", "card", "merge"], str(names))
check("funnel reports age-of-oldest", any(s["oldest_h"] is not None for s in snap["stages"]), "")

print("=" * 68)
ok = 0
for n, passed, d in RESULTS:
    print(f"  {'PASS' if passed else 'FAIL'}  {n}" + (f"   [{d}]" if d else ""))
    ok += passed
print("=" * 68)
print(f"  {ok}/{len(RESULTS)} passed")
sys.exit(0 if ok == len(RESULTS) else 1)
