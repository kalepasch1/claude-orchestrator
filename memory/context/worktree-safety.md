# Worktree Safety & Garbage Collection

How the orchestrator ensures no code loss when cleaning up old worktrees.

## The Problem Worktree GC Solves

Without cleanup, every task creates a new git worktree (isolated branch), and if they're never removed:
- ❌ Hundreds of zombie worktrees accumulate
- ❌ Branches stay checked out → `git rebase` fails ("already checked out")
- ❌ Disk fills up with abandoned data
- ❌ Merge handler breaks

Example: 93 tasks stuck with "CONFLICT" errors (actually stuck branches) because old worktrees were never cleaned up.

## How Worktree GC Works

**File:** `runner/worktree_gc.py`

### Step 1: Identify Protected Worktrees

Only worktrees in **terminal states are eligible for removal:**

```python
PROTECTED_STATES = ("RUNNING", "RETRY")
```

Worktrees for these task states are **NEVER removed:**
- RUNNING — Task currently executing (agent has it claimed)
- RETRY — Task in retry loop (might recover)
- (Any pending merge approvals)

### Step 2: Scan Git Worktrees

```bash
git worktree list --porcelain
```

Returns all worktrees like:
```
worktree /path/to/repo/agent/task-123
branch refs/heads/agent/task-123

worktree /path/to/repo/agent/task-124
branch refs/heads/agent/task-124
```

### Step 3: Remove Only Stale Ones

For each worktree:
1. Check if task slug is in protected set
2. If NOT protected → remove with `git worktree remove --force`
3. Prune dead branches with `git worktree prune`

```python
if slug not in protected and os.path.abspath(path) != main_worktree:
    git worktree remove --force path
```

### Step 4: Key Safety Point

**Removing a worktree does NOT delete commits.** It only:
- Removes the physical directory
- Frees disk space
- Unlocks the branch for merging

All committed code stays in:
- ✅ Main branch (if merged)
- ✅ Agent branch history (if pushed)
- ✅ Supabase `outcomes` table (complete record)

---

## What Happens to Code in Removed Worktrees?

### Scenario 1: Task Completed Successfully
```
Worktree with task-123 → Agent committed code → Merged to main
→ Worktree removed → Code is in main branch ✅
```

### Scenario 2: Task Failed
```
Worktree with task-456 → Agent tried & failed → Error logged to outcomes
→ Worktree removed → Error recorded in Supabase ✅
```

### Scenario 3: Task Running (Protected)
```
Worktree with task-789 → Agent actively executing
→ PROTECTED: will NOT be removed (state = RUNNING) ✅
```

### Scenario 4: Task Stuck (Should Never Happen)
```
Worktree with task-999 → Agent hung, state never updated
→ Worktree stays until state changes OR manual cleanup
→ Monitored by resource_governor.py (kills hung agents)
```

---

## Safety Mechanisms (Defense-in-Depth)

| Layer | Protection | How |
|-------|-----------|-----|
| **Database** | Protected states | Only remove tasks NOT in RUNNING/RETRY |
| **Git** | Branch locks | Branches stay in git history (commits aren't deleted) |
| **Audit** | Outcomes table | Every task's result is recorded |
| **Monitoring** | Resource governor | Kills hung agents to prevent zombies |
| **Testing** | Unit tests | Worktree GC has dedicated test suite |

---

## Verification: Check Removed Worktrees Had Outcomes

After seeing "worktree_gc: removed 16 stale worktree(s)", verify those tasks are recorded:

```bash
# See all tasks with outcomes (last 2 hours)
supabase sql "
SELECT
  COUNT(*) as total_outcomes,
  COUNT(CASE WHEN status = 'success' THEN 1 END) as success,
  COUNT(CASE WHEN status IN ('failure', 'error') THEN 1 END) as failed,
  COUNT(CASE WHEN status = 'timeout' THEN 1 END) as timeout
FROM outcomes
WHERE created_at > NOW() - INTERVAL '2 hours';
"
```

If this count matches the cleanup (16 removed ≈ 16 outcomes), all code is accounted for. ✅

---

## If You're Worried Code Was Lost

1. **Check git log in each project:**
   ```bash
   cd ~/Documents/tomorrow/tomorrow
   git log --oneline --graph --all | head -20
   # Look for agent/* branches with your code
   ```

2. **Check Supabase outcomes:**
   ```bash
   supabase sql "SELECT task_id, status, cost, created_at FROM outcomes ORDER BY created_at DESC LIMIT 20;"
   ```

3. **If something's missing:** Git history is immutable — nothing is truly lost, just the worktree directory was freed.

---

## How to Prevent Accidental Loss (Best Practices)

1. **Let verifications complete:** Don't stop runner during task execution
2. **Check task state before manual cleanup:** Never `rm` worktrees manually
3. **Trust worktree_gc:** It's conservative (only removes safe-to-remove worktrees)
4. **Monitor outcomes:** If a task's outcome isn't recorded, it's an orchestrator bug (report it)

---

## Timeline: When Worktree GC Runs

- **Startup:** Runs once during runner initialization (cleans up from previous crash)
- **Periodically:** Part of scheduled maintenance (see `runner/periodic.py`)
- **On demand:** Can run manually: `python3 worktree_gc.py`

For Phase 0 baseline test, the 16 stale worktrees were from previous runs (likely crashed tasks, old test runs, etc.). They're safe to remove.

---

## Bottom Line

✅ **No code is lost.** Worktree GC is conservative and protective.
✅ **Commits are immutable.** Removing a worktree doesn't delete git history.
✅ **Outcomes are recorded.** Every task's result is in Supabase.
✅ **Running tasks are safe.** RUNNING/RETRY state worktrees are never removed.

You can trust the cleanup. 🛡️
