#!/usr/bin/env python3
"""Fold the rescue-ref classification plus the dirty-worktree items into one
recovery ledger for audit fingerprint 1cfdd050a366..."""
import json, sys

FP = "1cfdd050a36666a6448e672ea5e3a99ca4f1efefc817675fbe79ac304bacd5e4"
SLUG = "chatgpt-local-reconcile-apparently-1cfdd050a366"
src = json.load(open("/Users/kpasch/Documents/beethoven/claude-orchestrator/.orch-tmp/rescue-classified.json"))

RECOVERED_REF = "5b8f8d2350a2002389953aebac3d343aeb8f27e1"
RECOVERED_PATHS = [
    "docs/recovery-ledgers/1500f0de3751-worktree-addendum.md",
    "docs/recovery-ledgers/1500f0de37513cf9f95ca4081511432b142a9b7362824a9120179a16515640bf-worktrees.json",
    "docs/recovery-ledgers/1500f0de37513cf9f95ca4081511432b142a9b7362824a9120179a16515640bf-worktrees.md",
    "docs/recovery-ledgers/1500f0de37513cf9f95ca4081511432b142a9b7362824a9120179a16515640bf.json",
    "docs/recovery-ledgers/1500f0de37513cf9f95ca4081511432b142a9b7362824a9120179a16515640bf.md",
    "docs/recovery-ledgers/45166d7f9f7a-notes.md",
    "docs/recovery-ledgers/45166d7f9f7a235573a2d901e0a00e4ecc57d58581e93442e892f857d0839d16.json",
    "docs/recovery-ledgers/45166d7f9f7a235573a2d901e0a00e4ecc57d58581e93442e892f857d0839d16.md",
    "scripts/reconcile-evidence.mjs",
    "server/api/foulkon/optimal-conclusion.post.ts",
    "tests/api/foulkon-optimal-conclusion.test.ts",
]

items = []
for i in src["items"]:
    o = {
        "kind": "orchestrator_rescue_ref",
        "source": "/Users/kpasch/Documents/apparently",
        "ref": i["ref"], "sha": i["sha"], "created_at": i["created_at"],
        "subject": i["subject"], "classification": i["classification"],
        "file_count": i["file_count"], "files": i["files"],
        "evidence": i["evidence"], "disposition": i["disposition"],
        "resulting_task": None, "resulting_branch": None, "resulting_commit": None,
    }
    if i["classification"] == "ACTIVE_IN_ANOTHER_TASK":
        o["resulting_branch"] = "origin/" + i.get("branch_hint", "")
    if i["classification"] == "RECOVERABLE_VALUE":
        o["absent_paths"] = i.get("absent_paths", [])
    items.append(o)

BRANCH = "agent/" + SLUG
COMMIT = sys.argv[1] if len(sys.argv) > 1 else None

# The two RECOVERABLE_VALUE refs: 005feb89 is a strict content subset of
# 5b8f8d23 for the two ledger files it shares, and its scripts/reconcile-evidence.mjs
# is the OLDER blob. Newest wins, so the recovery is taken wholly from 5b8f8d23
# and 005feb89 is dispositioned as covered by it rather than applied twice.
for o in items:
    if o["classification"] != "RECOVERABLE_VALUE":
        continue
    o["resulting_branch"] = BRANCH
    o["resulting_task"] = SLUG
    o["resulting_commit"] = COMMIT
    if o["sha"].startswith("5b8f8d23"):
        o["disposition"] = ("RECOVERED: 11 of its 12 absent paths restored onto "
                            "agent branch from this ref (docs/recovery-ledgers/README.md "
                            "skipped - zero bytes, no content to recover). "
                            "tests/api/foulkon-optimal-conclusion.test.ts: 42/42 pass; "
                            "tests/no-orphaned-test-files.test.ts 12/12; check:ai-calls OK.")
    else:
        o["disposition"] = ("covered by ref 5b8f8d23 (superset): its two ledger files are "
                            "byte-identical there and its scripts/reconcile-evidence.mjs blob "
                            "ef91283e is the OLDER of the two. Newest wins - recovered from "
                            "5b8f8d23, not applied twice.")

CONFLICT_TASK = "orch-rescue-conflicts-from-1cfdd050a366"
for o in items:
    if o["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK":
        o["resulting_task"] = CONFLICT_TASK

WT_LEDGER = ".orch/recovery-ledger-45ad3511beea.json"
WT = [
 (".claude/settings.json","ALREADY_PRESENT","tracked on origin/master; no local delta",None),
 (".landing-verify.sh","ACTIVE_IN_ANOTHER_TASK","landed at source HEAD by 48b08e52, in flight to master","chatgpt-local-reconcile-apparently-9ae6beb22d70"),
 ("triage-run-2026-08-11.md","ACTIVE_IN_ANOTHER_TASK","landed at source HEAD by 48b08e52, in flight to master","chatgpt-local-reconcile-apparently-9ae6beb22d70"),
 ("triage-run-2026-08-12.md","ACTIVE_IN_ANOTHER_TASK","landed at source HEAD by 48b08e52, in flight to master","chatgpt-local-reconcile-apparently-9ae6beb22d70"),
 ("server/utils/governance.ts","SUPERSEDED_BY_NEWER","pre-move legacy copy; shared/governance/index.ts replaced it 2026-08-13",None),
 (".convention-rules.json","SUPERSEDED_BY_NEWER","stale generated artifact of CLAUDE.md with no consumer in the repo; regenerate",None),
 (".supabase-applied.json","SUPERSEDED_BY_NEWER","local state file excluded by .gitignore:113; supabase/migrations/ is authoritative",None),
 ("triage-run-2026-08-11-HALTED.md","SUPERSEDED_BY_NEWER","excluded by .gitignore:112; successful same-date run already durable",None),
 (".probe2.mjs","SUPERSEDED_BY_NEWER","scratch playwright probe; tests/landing/sister-landing-structure.test.ts covers it",None),
 ("scripts/.tmp-dryrun-525.mjs","CONFLICTED_NEEDS_FOCUSED_TASK","raw SQL in .mjs violates CLAUDE.md; assertions hardcode migration 525","migration-dryrun-harness-from-45ad3511beea"),
 ("server/__tests__/api-exchange.test.ts","CONFLICTED_NEEDS_FOCUSED_TASK","endpoints absent on master; suite is entirely self-mocked","exchange-book-and-bids-endpoints-from-45ad3511beea"),
]
for path, cls, ev, task in WT:
    items.append({
        "kind": "dirty_worktree_file", "source": "/Users/kpasch/Documents/apparently",
        "path": path, "classification": cls, "evidence": ev,
        "disposition": ("carried over from the identical dirty-worktree evidence set already "
                        "reconciled under fingerprint 45ad3511beea; see " + WT_LEDGER),
        "resulting_task": task, "resulting_branch": None, "resulting_commit": None,
        "prior_ledger": WT_LEDGER,
    })

counts = {}
for i in items:
    counts[i["classification"]] = counts.get(i["classification"], 0) + 1

out = {
 "audit_fingerprint": FP, "task_slug": SLUG,
 "base": "origin/master", "base_sha": src["base_sha"],
 "evidence_sources": [
   {"kind": "dirty_worktree", "path": "/Users/kpasch/Documents/apparently",
    "head": "76386be19732374b892800718849b06d5e48e6f9",
    "branch": "consolidation/verified-merges-20260817", "snapshot_change_count": 11,
    "note": "same 11-file set as fingerprint 45ad3511beea; classifications carried over"},
   {"kind": "orchestrator_rescue_refs", "repo": "/Users/kpasch/Documents/apparently",
    "namespace": "refs/orch-rescue/", "snapshot_count": 365, "live_count": src["total"],
    "note": "snapshot recorded 365; the live namespace held %d at reconciliation time and "
            "all %d were enumerated and classified, per the instruction to enumerate the "
            "live source" % (src["total"], src["total"])},
 ],
 "source_mutated": False,
 "unknown_items": 0,
 "total_items": len(items),
 "counts": counts,
 "items": items,
}
json.dump(out, open(sys.argv[2], "w"), indent=1)
print("items", len(items), json.dumps(counts))
