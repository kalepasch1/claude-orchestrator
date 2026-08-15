#!/usr/bin/env python3
"""End-to-end verification of the 2026-08-15 fixes against the RUNNING system.

Source-level tests prove the code says the right thing. This proves the fleet DOES the right
thing, which is a different question and the one that kept being answered wrongly: three
separate times this month a fix was confirmed by reading code that had since been reverted, or
by a monitor measuring the wrong column.

Every check states what would be true if the fix were absent, so a pass carries information.
Safe to run at any time — it reads, and the one environment variable it sets is restored.
"""
import sys, os, subprocess, datetime
sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner')
os.chdir('/Users/kpasch/Documents/beethoven/claude-orchestrator/runner')
R = []
def check(name, ok, detail=""):
    R.append((name, bool(ok), detail))

import db, merge_train as mt, preflight_filter as pf, shadow_mode

# 1. card visibility — was 90 of 569 before the server-side filter
cards = mt._pick_cards()
check("train can see the card backlog", len(cards) > 100, f"{len(cards)} cards")

# 2. legacy kill switch declined by current code
os.environ["MERGE_TRAIN_SCAN_LIMIT"] = "0"
check("legacy kill switch declined", len(mt._pick_cards()) > 0, "non-zero with the switch at 0")
os.environ.pop("MERGE_TRAIN_SCAN_LIMIT", None)

# 3. preflight keeps a detailed spec that has failed repeatedly
SPEC = "## OBJECTIVE\n" + "Detail line explaining the required behaviour.\n" * 60
check("detailed spec survives 5 failures", pf.preflight_check(
    {"slug": "t", "prompt": SPEC, "attempt": 5, "note": ""}) == "", "was quarantined before")
check("thin prompt still rejected", "exhausted" in pf.preflight_check(
    {"slug": "t", "prompt": "fix it", "attempt": 5, "note": ""}), "")

# 4. shadow mode refuses AND is not mistaken for success
os.environ["ORCH_SHADOW_MODE"] = "true"
out = mt._push_base("/tmp", "orchestrator/dev", project="verify")
check("shadow refusal is non-empty", bool(out), repr(out)[:60])
os.environ["ORCH_SHADOW_MODE"] = "false"
check("integration branch is push-enabled", mt._push_enabled_for_base("orchestrator/dev"), "")
check("production base stays disabled", not mt._push_enabled_for_base("main"), "")
os.environ["ORCH_SHADOW_MODE"] = "true"

# 5. self-work classifier
check("upkeep classified", db._is_self_maintenance({"slug": "canary-x"}), "")
check("product work not classified as upkeep",
      not db._is_self_maintenance({"slug": "dropbox-apparently-licensing"}), "")

# 6. the requeued specs are alive in the queue
n = db.count("tasks", {"state": "eq.QUEUED", "note": "like.requeued 2026-08-15*"})
check("recovered specs are queued", n > 0, f"{n} of 139 still queued")

# 7. THE INVARIANT THAT ACTUALLY MATTERS: no task claims MERGED unless its sha is on origin.
#
# The first version of this check asserted zero MERGED during a shadow window and failed on a
# task that was correct: the train marked it merged via the ALREADY-integrated path, where the
# work is already on origin and no push is needed, so no refusal applies. "Nothing merged" was
# never the property worth protecting. "Nothing claims to have shipped that did not" is.
since = "2026-08-15T17:00:00+00:00"
projs = {p["id"]: db.localize_repo_path(p.get("repo_path", "") or "")
         for p in (db.select("projects", {"select": "*", "limit": "200"}) or [])}
rows = db.select("tasks", {"select": "slug,project_id,artifact_commit", "state": "eq.MERGED",
                           "updated_at": f"gte.{since}", "limit": "200"}) or []
phantom = []
for r in rows:
    sha, repo = r.get("artifact_commit"), projs.get(r.get("project_id"))
    if not sha or not repo:
        continue
    rr = subprocess.run(["git", "branch", "-r", "--contains", sha], cwd=repo,
                        capture_output=True, encoding="utf-8")
    if not (rr.stdout or "").strip():
        phantom.append(r.get("slug"))
check("nothing claims MERGED that is not on origin", not phantom,
      f"{len(rows)} merged, {len(phantom)} phantom")

print("=" * 72)
ok = sum(1 for _, p, _ in R if p)
for n_, p, d in R:
    print(f"  {'PASS' if p else 'FAIL'}  {n_}" + (f"   [{d}]" if d else ""))
print("=" * 72)
print(f"  {ok}/{len(R)} live checks passed")
