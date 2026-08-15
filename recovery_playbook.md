# Causal Outcome Feedback: Zero-Token Recovery Playbook

**Date:** 2026-08-03  
**Status:** ACTIVE  
**Scope:** Causal outcome feedback system recovery and state inspection

## Overview

This playbook enables recovery of the causal-outcome-feedback system using only local inspection and git operations — **zero API calls, zero network, zero spend**. It is designed for fleet-down scenarios when the runner cannot reach Supabase or needs to recover from stale worktree/branch state.

## Quick Recovery Flow (5 min, local-only)

```bash
# 1. Check current git state
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
git status
git branch -a | grep -E "agent/|chatgpt/"

# 2. Inspect stale worktrees
ls -la /Users/kpasch/Documents/beethoven-wt/
du -sh /Users/kpasch/Documents/beethoven-wt/*

# 3. Check for pending patches (ChatGPT sandbox handoff)
ls -la ~/Documents/chatgpt-dropbox/

# 4. Verify test file exists and runs
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/runner
python3 -m pytest tests/test_causal_feedback.py -v --tb=short

# 5. Verify integration point is in place
grep -n "causal_feedback" runner.py
```

## Phase 1: Branch Inspection (Local Git)

### List all agent branches
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
git branch -a | grep agent/
git branch -a | grep chatgpt/
```

**Expected output:** Branches prefixed with `agent/` (from Mac runner) or `chatgpt/` (from ChatGPT sandbox).
**What to look for:**
- Stale branches older than 7 days (from `git log --oneline -n 1 <branch>`)
- Branches with no corresponding PR (check `git branch -r -v --track`)

### Clean up stale branches locally
```bash
# List branches sorted by last commit
git for-each-ref --sort=-committerdate refs/heads/ | grep -E "agent/|chatgpt/"

# Delete local stale branches (example: older than 7 days)
git branch -d agent/old-stale-branch-name
```

**Safety:** Local deletion only. Remote branches remain until explicitly pushed.

### Inspect recent commits
```bash
git log --oneline -n 30 --all | grep -E "agent/|improve-|causal"
git log --graph --all --oneline --decorate -n 50
```

## Phase 2: Worktree Cleanup (Local Disk)

### List active and stale worktrees
```bash
# Check what's on disk
ls -la /Users/kpasch/Documents/beethoven-wt/
du -sh /Users/kpasch/Documents/beethoven-wt/* | sort -rh

# Check which worktrees are used by running git commands
cd /Users/kpasch/Documents/beethoven-wt
for d in */; do
  echo "=== $d ==="
  cd "$d"
  git rev-parse --abbrev-ref HEAD 2>&1 || echo "not a git repo"
  cd ..
done
```

**Expected output:** Directories named like `{task-slug}-{random}` or `{task-id}-{random}`.
**What to look for:**
- Directories with no `.git/` subdirectory (corrupted)
- Directories untouched for >7 days (`stat -f "%Sm %N" /path/to/dir`)

### Remove stale worktrees (safe)
```bash
# Remove a specific stale worktree (after verifying it's not actively used)
rm -rf /Users/kpasch/Documents/beethoven-wt/stale-slug-abc123

# Remove all worktrees with no git repo
for d in /Users/kpasch/Documents/beethoven-wt/*/; do
  if [ ! -d "$d/.git" ]; then
    echo "Removing non-git directory: $d"
    rm -rf "$d"
  fi
done

# Check git worktree list
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
git worktree list
git worktree prune  # clean up stale entries
```

**Safety:** Deleting a worktree does NOT delete the branch. Always verify the branch still exists locally or remotely before removing the worktree.

## Phase 3: Patch Re-application (ChatGPT Sandbox)

### Check for pending patches
```bash
ls -la ~/Documents/chatgpt-dropbox/
ls -la ~/Documents/chatgpt-dropbox/_applied/
ls -la ~/Documents/chatgpt-dropbox/_failed/
```

**Expected:** Patch files are `.patch`, `.diff`, `.tar.gz`, or `.zip` format.
**What to look for:**
- Files stuck in the dropbox that haven't been moved to `_applied/` or `_failed/` for >1 hour
- Error logs in `_logs/bridge.log` indicating repeated failures

### Manually apply a patch (if bridge is stuck)
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator

# Option A: Use the chatgpt-patch CLI (if available)
chatgpt-patch ~/Documents/chatgpt-dropbox/example-slug.patch

# Option B: Apply patch directly (if worktree directory is known)
cd /Users/kpasch/Documents/beethoven-wt/example-slug-abc123
patch -p1 < ~/Documents/chatgpt-dropbox/example-slug.patch
git add .
git commit -m "Applied ChatGPT patch: example-slug"
```

**Safety:**
- Never force-apply a patch over uncommitted changes. Use `git stash` first.
- Verify patch applies cleanly with `git apply --check` before committing.

### Move processed patches to archive
```bash
# Mark as applied
mv ~/Documents/chatgpt-dropbox/example-slug.patch ~/Documents/chatgpt-dropbox/_applied/

# Mark as failed (if manual intervention was needed)
mv ~/Documents/chatgpt-dropbox/failed-slug.patch ~/Documents/chatgpt-dropbox/_failed/
```

## Phase 4: Test Verification (Local-Only)

### Run test suite
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/runner
python3 -m pytest tests/test_causal_feedback.py -v --tb=short
```

**Expected:** ✓ 50+ test cases passing (test_causal_feedback.py: 45+ cases)

### Check test coverage
```bash
python3 -m pytest tests/test_causal_feedback.py --cov=causal_feedback --cov-report=term-missing
```

**Expected:** ≥80% line coverage on causal_feedback.py

### Verify integration hook
```bash
grep -A5 "causal_feedback.write" runner.py
```

**Expected:** Code at line 275-290 (approximately) shows conditional call to `causal_feedback.write()`.

## Phase 5: Metrics Snapshot Validation

### Check for bottleneck signals in task metadata
```bash
# This is a local inspection only — no DB calls
# Tasks can inject _bottleneck_key and _signal_before/_signal_after into the task row
# before calling set_state() with "DONE" state.

# Example usage (from framework code):
#   task_row["_bottleneck_key"] = "cycle_time_hours"
#   task_row["_signal_before"] = 96.4
#   task_row["_signal_after"] = 42.1
#   causal_feedback.write(...task_row...)
```

**How to inject signals:** Framework code or remediation tasks should populate `_bottleneck_key`, `_signal_before`, and `_signal_after` on the task row before task completion. The causal_feedback integration looks for these fields and skips the write if they're missing (fail-soft).

## Phase 6: Configuration Validation

### Verify environment variables are safe
```bash
grep "ORCH_CAUSAL" runner/.env 2>/dev/null || echo "No causal config in .env"
grep "ORCH_CAUSAL" ~/.bash_profile ~/.zsh_profile 2>/dev/null || echo "No causal config in shell"

# Check defaults
grep "ORCH_CAUSAL" runner/causal_feedback.py
```

**Expected config keys (safe, no secrets):**
- `ORCH_CAUSAL_ENABLED` — "true" or "false" (default: true)
- `ORCH_CAUSAL_CONFIDENCE_FLOOR` — 0.0-1.0 (default: 0.8)
- `ORCH_CAUSAL_NONBLOCKING` — "true" or "false" (default: true)

**Dangerous patterns (REJECT):** Any key containing credentials, API keys, or plaintext secrets → NEVER commit.

## Phase 7: Metrics Backfill (Optional, Zero-Token)

### Understand outcome classification
```bash
# Open the file and read the _classify_outcome function
cat runner/causal_feedback.py | grep -A20 "def _classify_outcome"
```

**Thresholds:**
- `positive`: signal_after < signal_before × 0.95 (>5% improvement)
- `neutral`: ±5% change
- `negative`: signal_after > signal_before × 1.05 (>5% worsening)
- `pending`: missing or invalid signals

### Manually log a feedback record (if needed)
```bash
# This REQUIRES Supabase connectivity (not zero-token)
# Use ONLY if the integration is restored and you need to backfill historical data

python3 << 'EOF'
import causal_feedback
result = causal_feedback.write(
    bottleneck_key="cycle_time_hours",
    remediation_slug="improve-cycle-time",
    signal_before=96.4,
    signal_after=42.1,
    confidence=0.85
)
print(f"Written: {result}")
EOF
```

**Note:** This requires live DB access and IS NOT zero-token. Use only during normal operation.

## Troubleshooting

### Problem: `test_causal_feedback.py` not found
**Solution:**
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/runner
ls -la tests/test_causal_feedback.py
# If missing, re-apply the patch or re-run the implementation task
```

### Problem: Tests fail with import errors
**Solution:**
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/runner
python3 -c "import causal_feedback; print(causal_feedback.__file__)"
# Verify causal_feedback.py is in the same directory as runner.py
```

### Problem: Stale worktree won't delete
**Solution:**
```bash
# Check if it's still in use by git
git worktree list

# If stuck in list, prune it
git worktree prune

# Force remove if needed (DANGEROUS — only if you're sure the branch is safe)
rm -rf /Users/kpasch/Documents/beethoven-wt/stuck-worktree
git branch -D stuck-branch
```

### Problem: Integration hook not working
**Solution:**
```bash
grep -n "ORCH_CAUSAL_ENABLED" runner/runner.py
# Verify the env var check is correct (line ~276)
# Verify causal_feedback module is importable
python3 -c "import sys; sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner'); import causal_feedback; print('OK')"
```

## Acceptance Checklist (Zero-Token)

- [ ] All branches in `git branch -a` are accounted for (no orphaned branches)
- [ ] Worktree directory `/Users/kpasch/Documents/beethoven-wt/` is clean (no stale entries)
- [ ] No patches stuck in `~/Documents/chatgpt-dropbox/` for >1 hour
- [ ] `pytest tests/test_causal_feedback.py` passes all 45+ cases with ≥80% coverage
- [ ] `grep "causal_feedback" runner.py` shows integration hook at line ~275
- [ ] No hardcoded secrets in `ORCH_CAUSAL_*` config keys
- [ ] This playbook is reachable from root README (or CLAUDE.md backlink)

## Related Documentation

- **Causal Feedback Module:** `runner/causal_feedback.py` — write(), lookup(), for_remediation()
- **Database Schema:** `supabase/migrations/20260803_causal_outcome_feedback.sql`
- **Test Suite:** `runner/tests/test_causal_feedback.py` (45+ cases)
- **Integration Point:** `runner/runner.py` line ~275 (task completion hook)
- **CLAUDE.md:** Project instructions and conventions

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-08-03 | Claude | Initial zero-token recovery playbook |
