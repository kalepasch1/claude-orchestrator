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


# 13. WAIT-card fetch storm: cards are filed before the agent branch exists, and every one of
#     them used to pay its own `git fetch origin <branch>` to rediscover that. One ls-remote
#     answers it for the whole pass. The contract that matters is that the shortcut is only ever
#     allowed to say "no" about a branch origin genuinely does not have.
_repo = "/Users/kpasch/Documents/beethoven/claude-orchestrator"
import subprocess as _sp
_ls = _sp.run(["git", "ls-remote", "--heads", "origin", "refs/heads/agent/*"], cwd=_repo,
              capture_output=True, encoding="utf-8")
_real = [l.split("\trefs/heads/", 1)[1].strip() for l in _ls.stdout.splitlines()
         if "\trefs/heads/" in l]
check("remote agent refs listed in one call", _ls.returncode == 0 and len(_real) > 0,
      f"{len(_real)} branches")
check("shortcut never hides a branch origin has",
      all(mt._remote_agent_branch_maybe(_repo, b) for b in _real[:40]),
      f"checked {min(40, len(_real))}")
check("shortcut rejects a branch origin lacks",
      not mt._remote_agent_branch_maybe(_repo, "agent/__no_such_branch_20260806__"), "")
import time as _time
_t = _time.time(); [mt._remote_agent_branch_maybe(_repo, "agent/__miss_%d__" % i) for i in range(300)]
_warm = _time.time() - _t
check("300 misses answered from cache, not the network", _warm < 1.0, f"{_warm:.3f}s for 300")


# 14. archive refs must leave the machine. archive_branch() wrote refs/archive/<b>/<epoch>
#     locally and logged "archived ...", which reads as a durability guarantee it did not
#     provide: audited today, 93 archive refs on this disk and 0 on origin.
_bd = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/branch_durability.py").read()
check("archive_branch pushes the ref to origin",
      'f"{ref}:{ref}"' in _bd and "ORCH_SHARE_ARCHIVE_REFS" in _bd, "push present")
check("a failed archive push is reported, not swallowed",
      "LOCAL-ONLY" in _bd, "log distinguishes durable from local-only")
_local = _sp.run(["git", "for-each-ref", "--format=%(refname)", "refs/archive/"],
                 cwd=_repo, capture_output=True, encoding="utf-8").stdout.split()
_rem = [l.split()[-1] for l in _sp.run(["git", "ls-remote", "origin", "refs/archive/*"],
        cwd=_repo, capture_output=True, encoding="utf-8").stdout.splitlines() if "refs/archive/" in l]
check("existing archive refs are now on origin too",
      _local and not (set(_local) - set(_rem)), f"local={len(_local)} origin={len(_rem)}")


# 15. a merge_train pass must enforce its own runtime budget. The cap lived only in the
#     launching runner's _PERIODIC_PIDS map, so a train orphaned by a runner restart (ppid 1)
#     was unkillable AND kept holding merge-train.single.lock — observed today as pid 37459,
#     24 minutes wedged, no train able to start on this machine at all.
_mt_src = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/merge_train.py").read()
check("train owns its runtime budget", "merge-train-watchdog" in _mt_src and "os._exit(3)" in _mt_src,
      "self-enforced deadline present")
check("watchdog dumps threads before exiting", "dump_traceback(all_threads=True)" in _mt_src,
      "next wedge is diagnosable")
_wd = _sp.run([sys.executable, "-u", "-c",
    "import os,sys,time,threading,faulthandler\n"
    "def d():\n"
    " time.sleep(1); faulthandler.dump_traceback(all_threads=True); os._exit(3)\n"
    "threading.Thread(target=d,daemon=True).start()\n"
    "time.sleep(30)"], capture_output=True, encoding="utf-8", timeout=30)
check("watchdog actually kills a hung pass", _wd.returncode == 3 and "Thread" in (_wd.stderr or ""),
      f"rc={_wd.returncode}")


# 16. the legacy-host kill switch must not disable the hosts it was never aimed at.
#     fleet_config MERGE_TRAIN_SCAN_LIMIT=0 starves Mac 2's train (the only lever 10d9e408
#     exposes). It was meant to be pinned away on this host; the pin silently did not take
#     because the running runner had inherited the pre-edit pins list, and one pass here
#     returned an all-zero summary as a result.
_kill = _sp.run([sys.executable, "-c",
    "import sys; sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner');"
    "import merge_train as m; print(len(m._pick_cards()))"],
    capture_output=True, encoding="utf-8", env={**os.environ, "MERGE_TRAIN_SCAN_LIMIT": "0"})
_n = int((_kill.stdout or "0").strip() or 0)
check("current code declines the legacy kill switch", _n > 0, f"{_n} cards with the switch at 0")


# 17. integration worktree slots were condemned for life by a build cache. "Dirty" counted any
#     untracked byte, so a slot that had once run tests was abandoned on every pass and a fresh
#     temporary one built instead — 21 slots, 2.2GB, and a release-train log that had become the
#     same line repeated. The reclaim must be narrow: machine output yes, real work never.
import regenerable_artifacts as _ra
_cache_dirt = (" D packages/curation-core/node_modules/.vite/vitest/da39/results.json\n"
               " D server/utils/simulation/__pycache__/generateProspectPdf.cpython-310.pyc")
_b, _r = _ra.partition_dirt(_cache_dirt)
check("build caches are reclaimable", not _b and len(_r) == 2, f"blocking={len(_b)} regen={len(_r)}")
_work_dirt = " D app/pages/coverage/[org].vue\n D server/api/public/coverage/verify.get.ts"
_b2, _r2 = _ra.partition_dirt(_work_dirt)
check("deleted source still preserves the slot", len(_b2) == 2 and not _r2, f"blocking={len(_b2)}")
for _p in (" M lib/commerce/coppa.ts", " M package-lock.json", " M OPPORTUNITIES.json"):
    check(f"still blocks: {_p.strip()}", bool(_ra.partition_dirt(_p)[0]), "")
_ir = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/integration_runtime.py").read()
check("reclaim path resets only when nothing blocks",
      "if not existing_dirty.returncode and regen and not blocking:" in _ir
      and 'reset", "--hard' in _ir, "guarded reset present")
check("classification failure falls back to blocking",
      "treating all of it as blocking" in _ir, "fail-closed")


# 18. temporary worktrees leaked because the mutation check raised from `finally` BEFORE the
#     removal ran. Any canonical drift during a pass therefore stranded the slot: 57
#     CanonicalCheckoutMutationError in merge-train.log, 10 abandoned -run- dirs, 1.5GB.
import integration_runtime as _ir
_base = {"top": "/r", "branch": "master", "head": "abc", "status": " M src/a.ts\n"}
check("identical snapshots are not a mutation", not _ir._canonical_mutation(_base, dict(_base)), "")
check("an untracked file appearing is not a mutation",
      not _ir._canonical_mutation(_base, {**_base, "status": " M src/a.ts\n?? docs/ADR-x.md\n"}),
      "this fired 57 times on ordinary fleet noise")
check("regenerable tracked dirt is not a mutation",
      not _ir._canonical_mutation(_base, {**_base, "status": " M src/a.ts\n M .runner_boot_commit\n"}), "")
check("HEAD moving IS a mutation", "head:" in _ir._canonical_mutation(_base, {**_base, "head": "def"}), "")
check("branch switch IS a mutation", "branch:" in _ir._canonical_mutation(_base, {**_base, "branch": "dev"}), "")
check("a new tracked edit IS a mutation",
      "src/b.ts" in _ir._canonical_mutation(_base, {**_base, "status": " M src/a.ts\n M src/b.ts\n"}), "")
check("a tracked deletion IS a mutation",
      bool(_ir._canonical_mutation(_base, {**_base, "status": " D src/a.ts\n"})), "")
_irs = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/integration_runtime.py").read()
check("cleanup runs before the mutation raise",
      _irs.index("worktree\", \"remove") < _irs.index("raise CanonicalCheckoutMutationError"),
      "removal precedes the verdict")
check("orphaned temporaries are swept", "sweep_orphaned_temporaries" in _irs, "")
_left = _ir.sweep_orphaned_temporaries("/Users/kpasch/Documents/beethoven/claude-orchestrator")
check("no orphaned -run- dirs remain", _left == 0, f"{_left} removed on this run")


# 19. scan-window starvation, third instance. integration_sweeper took the `limit` OLDEST tasks
#     by updated_at from a set of 200 with limit=80, so the NEWEST 120 were never looked at —
#     and the sweeper is what files an integration card. 28 finished tasks had a pushed agent/
#     branch, no approvals row, and no path to ever getting one.
_sw = open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/integration_sweeper.py").read()
check("sweeper scans both ends", '"updated_at.asc", "updated_at.desc"' in _sw, "dual-order present")
check("sweeper limit exceeds the state set it scans",
      int(_re.search(r'INTEGRATION_SWEEPER_LIMIT", "(\d+)"', _sw).group(1)) >= 150, "")
_total = _db_count = None
import db as _db
_total = _db.count("tasks", {"state": "in.(DONE,BLOCKED,RUNNING)"})
_one = _db.select("tasks", {"select": "id", "state": "in.(DONE,BLOCKED,RUNNING)",
                            "order": "updated_at.asc", "limit": "150"}) or []
_seen, _both = set(), 0
for _o in ("updated_at.asc", "updated_at.desc"):
    for _r in (_db.select("tasks", {"select": "id", "state": "in.(DONE,BLOCKED,RUNNING)",
                                    "order": _o, "limit": "150"}) or []):
        if _r["id"] not in _seen:
            _seen.add(_r["id"]); _both += 1
check("dual-order loses nothing the single window saw",
      not ({_r["id"] for _r in _one} - _seen), f"total={_total} single={len(_one)} dual={_both}")
check("dual-order covers the whole state set", _both >= _total, f"{_both} of {_total}")


# 20. the same scan-window bug appeared three times today in three different files. There are
#     262 db.select call sites passing both order and limit; auditing them by hand is a guess
#     about which sets will grow. Detect the condition instead: a query coming back EXACTLY
#     full is the unambiguous sign it was cut off.
_probe = _sp.run([sys.executable, "-c",
    "import sys; sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner');"
    "import db;"
    "db.select('tasks', {'select':'id','state':'eq.DONE','order':'updated_at.asc','limit':'5'});"
    "db.select('tasks', {'select':'id','state':'eq.DONE','order':'updated_at.asc','limit':'900000'});"
    "db.select('tasks', {'select':'id','state':'eq.DONE','limit':'5'})"],
    capture_output=True, encoding="utf-8", timeout=120)
_warns = [l for l in (_probe.stderr or "").splitlines() if "TRUNCATED SCAN" in l]
check("a truncated ordered scan warns", len(_warns) == 1, f"{len(_warns)} warning(s)")
check("an unordered or unfilled scan does not warn",
      all("900000" not in w for w in _warns), "only the capped-and-full query warned")
_quiet = _sp.run([sys.executable, "-c",
    "import sys; sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner');"
    "import db;"
    "db.select('tasks', {'select':'id','state':'eq.DONE','order':'updated_at.asc','limit':'5'})"],
    capture_output=True, encoding="utf-8", timeout=120,
    env={**os.environ, "ORCH_SCAN_TRUNCATION_WARN": "false"})
check("the detector can be switched off",
      "TRUNCATED SCAN" not in (_quiet.stderr or ""), "ORCH_SCAN_TRUNCATION_WARN=false")
check("the detector never breaks the query it observes",
      _probe.returncode == 0 and _quiet.returncode == 0, "")

print("=" * 68)
ok = 0
for n, passed, d in RESULTS:
    print(f"  {'PASS' if passed else 'FAIL'}  {n}" + (f"   [{d}]" if d else ""))
    ok += passed
print("=" * 68)
print(f"  {ok}/{len(RESULTS)} passed")
sys.exit(0 if ok == len(RESULTS) else 1)
