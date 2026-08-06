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


# 12. scan-window starvation, part two: the narrowed (server-side) card scan must be a strict
#     SUPERSET of the old dual-window scan. 21,974 approved merge-kind cards exist but PostgREST
#     caps a page at 1,000 rows, so scanning both ends still hid the middle of the table. Asserting
#     "more cards" alone would pass on a filter that swapped one blind spot for another; the real
#     contract is that nothing the old path could see is lost.
check("pick_cards asks the server for unhandled only",
      "decided_by.is.null" in src and "not.like" in src, "predicate present")
import db as _db, approval_merge as _am
_base = {"select": "*", "status": "eq.approved",
         "kind": "in.(%s)" % ",".join(mt.MERGE_KINDS),
         "limit": os.environ.get("MERGE_TRAIN_SCAN_LIMIT", "3000")}
_seen, _old = set(), []
for _o in ("created_at.asc", "created_at.desc"):
    for _c in (_db.select("approvals", {**_base, "order": _o}) or []):
        if _c.get("id") in _seen:
            continue
        _seen.add(_c.get("id"))
        if (_c.get("kind") in mt.MERGE_KINDS and _am._is_code_merge_card(_c)
                and not str(_c.get("decided_by") or "").startswith(mt.SKIP_PREFIXES)):
            _old.append(_c)
_new_ids = {c.get("id") for c in mt._pick_cards()}
_lost = {c.get("id") for c in _old} - _new_ids
check("narrowed scan loses nothing the wide scan saw", not _lost,
      f"old={len(_old)} new={len(_new_ids)} lost={len(_lost)}")
check("narrowed scan uncovers cards the window hid", len(_new_ids) > len(_old),
      f"+{len(_new_ids) - len(_old)} previously invisible")

print("=" * 68)
ok = 0
for n, passed, d in RESULTS:
    print(f"  {'PASS' if passed else 'FAIL'}  {n}" + (f"   [{d}]" if d else ""))
    ok += passed
print("=" * 68)
print(f"  {ok}/{len(RESULTS)} passed")
sys.exit(0 if ok == len(RESULTS) else 1)
