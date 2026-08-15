#!/usr/bin/env python3
"""How many live tasks would a global repair ceiling terminate, and how much work is it burning?"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

rows = db.select("tasks", {
    "select": "slug,state,note,log_tail,remediation_count,transient_retries,attempt,updated_at",
    "state": "in.(QUEUED,RETRY,BLOCKED,CONFLICT,TESTFAIL,RUNNING)",
    "limit": "5000",
}) or []
print("live tasks: %d" % len(rows))

def rc(r):
    return int(r.get("remediation_count") or 0)

def blind(r):
    return not str(r.get("log_tail") or "").strip()

hist = collections.Counter(rc(r) for r in rows)
tot = len(rows)
print("\nremediation_count histogram (live queue):")
run = 0
for k in sorted(hist):
    run += hist[k]
    print("  rc=%-3d %6d   cumulative %5.1f%%" % (k, hist[k], 100.0 * run / tot))

print("\nblind (no log_tail) share of live tasks: %d / %d = %.0f%%"
      % (sum(1 for r in rows if blind(r)), tot, 100.0 * sum(1 for r in rows if blind(r)) / tot))

print("\nceiling impact (tasks that would go terminal instead of re-queueing):")
for c in (4, 6, 8, 10, 12):
    n = sum(1 for r in rows if rc(r) >= c)
    print("  global ceiling %-3d -> %4d tasks (%.1f%% of live queue)" % (c, n, 100.0 * n / tot))
for c in (2, 3, 4, 5):
    n = sum(1 for r in rows if blind(r) and rc(r) >= c)
    print("  blind  ceiling %-3d -> %4d tasks (%.1f%% of live queue)" % (c, n, 100.0 * n / tot))

burn = sum(rc(r) for r in rows)
print("\ntotal repair cycles already spent on the live queue: %d" % burn)
print("cycles spent on tasks at rc>=8: %d" % sum(rc(r) for r in rows if rc(r) >= 8))
print("cycles spent blind at rc>=3:    %d" % sum(rc(r) for r in rows if blind(r) and rc(r) >= 3))

print("\nworst 12 by remediation_count:")
for r in sorted(rows, key=rc, reverse=True)[:12]:
    print("  rc=%-3d tr=%-3s att=%-3s blind=%-5s %-46s %s"
          % (rc(r), r.get("transient_retries"), r.get("attempt"), blind(r),
             (r.get("slug") or "")[:46], r.get("state")))
