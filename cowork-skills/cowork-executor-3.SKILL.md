---
name: cowork-executor
description: High-throughput autonomous task executor for claude-orchestrator. Claims 5 QUEUED tasks atomically, reads pre-optimized enriched prompts, implements ALL with Claude, pushes branches, batch-deploys Vercel. Zero skip. Runs every 2 minutes.
---

# Cowork Executor v6.5 — Auto-Loop · Claude-Only · Enriched Prompts · Batch Vercel · Zero Skip

**CONTINUOUS LOOP: After completing a batch, immediately loop back to Step 0b and claim the next batch. NEVER stop after a single batch. Only write `<run-summary>` and stop when Step 1 returns 0 rows (empty queue).**

**`<run-summary>` IS FORBIDDEN until the queue is empty. Writing one while tasks remain ends the session early and creates zombies.**

**ZERO SKIP: Every claimed task gets code committed and pushed. Sensitivity, vagueness, secrets — none are skip reasons.**

## Architecture
This executor is the DEPLOYMENT layer. Other AI vendors (OpenAI, Gemini, Ollama) pre-process and pre-draft tasks in the queue via runner.py. `cowork_assemble.py` surfaces that pre-work. Claude (this session) reads it, implements the final code, pushes to repo, deploys to Vercel. Fast because the heavy thinking is already done upstream.

## Tools
- **Supabase MCP** (`execute_sql`, project_id `eatfwdzfurujcuwlhdgj`)
- **Desktop Commander MCP** (`read_file`, `write_file`, `edit_block`, `start_process`)

## Project Repos
```
beethoven      /Users/kpasch/Documents/beethoven/claude-orchestrator   master
tomorrow       /Users/kpasch/Documents/tomorrow/tomorrow               main
apparently     /Users/kpasch/Documents/apparently                      master
smarter        /Users/kpasch/Documents/smarter                         main
pareto-2080    /Users/kpasch/Documents/pareto/2080                     main
darwn          /Users/kpasch/Documents/darwn/darwn                     medicalOnly
racefeed       /Users/kpasch/Documents/galop/racefeed                  master
santas-secret-workshop  /Users/kpasch/Documents/hisanta               master
sustainable-barks       /Users/kpasch/Documents/Sustainable_Barks     main
```

---

## Step 0: FETCH KEYS + RELEASE ZOMBIES (once per session)

### 0a. Keys (first loop only — cache for reuse)
```sql
NEVER read GITHUB_PAT / VERCEL_TOKEN / API keys from `fleet_config`, and NEVER write
them there. Those rows were purged in the 2026-08-02 plaintext-credential incident and a
DB guard now rejects them, so the SELECT returns nothing — which silently produced an
empty token, a broken origin URL and a failed push on EVERY run of all 16 executors.
git uses the osxkeychain credential helper against each repo's existing clean origin;
the vercel CLI is already logged in. Use the ambient credentials as-is.

### 0b. Release zombies from crashed/rate-limited sessions (every loop)
```sql
UPDATE tasks SET state='QUEUED', note='v6.5: zombie released — heartbeat stale >90min'
WHERE state='RUNNING'
  AND updated_at < now() - interval '90 minutes'
  AND account LIKE 'cowork-executor%';
```

---

## Step 1: ATOMIC CLAIM — 5 tasks, single CTE

```sql
WITH candidates AS (
  SELECT t.id
  FROM tasks t
  JOIN projects p2 ON p2.id = t.project_id
  WHERE t.state = 'QUEUED'
    AND t.kind NOT IN ('speculative')
    AND (t.deps IS NULL OR array_length(t.deps,1) IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM unnest(t.deps) AS dep
           WHERE dep NOT IN (
             SELECT t2.slug FROM tasks t2
             WHERE t2.project_id = t.project_id AND t2.state IN ('DONE','MERGED')
           )
         ))
  ORDER BY
    -- OPERATOR-ORIGIN FIRST (2026-08-04). Drop-box asks and anything with an attributed
    -- submitter are the owner's own directives: they outrank every machine-generated
    -- repair task. Previously they fell into ELSE(6), behind recovery/toolchain/bugfix/
    -- build/canary churn, so 16 executors burned tokens on the fleet's self-repair loop
    -- while the operator's queue never moved.
    CASE WHEN t.slug LIKE 'dropbox-%' THEN 0
         WHEN t.submitted_by IS NOT NULL THEN 0
         WHEN COALESCE(t.submitted_by_label,'') <> '' THEN 0
         ELSE 1 END,
    -- Then the owner's stated portfolio order.
    CASE p2.name
      WHEN 'apparently'    THEN 1
      WHEN 'apparently-law' THEN 2
      WHEN 'tomorrow'      THEN 3
      WHEN 'beethoven'     THEN 4
      WHEN 'smarter'       THEN 5
      WHEN 'illuminati'    THEN 6
      WHEN 'pareto-2080'   THEN 7
      ELSE 8 END,
    CASE t.kind
      WHEN 'recovery'         THEN 1
      WHEN 'toolchain-repair' THEN 2
      WHEN 'bugfix'           THEN 3
      WHEN 'build'            THEN 4
      WHEN 'canary'           THEN 5
      ELSE 6
    END,
    t.confidence DESC NULLS LAST,
    t.attempt ASC, t.id ASC
  LIMIT 5
  FOR UPDATE OF t SKIP LOCKED
),
claimed AS (
  UPDATE tasks SET state='RUNNING', account='cowork-executor-v6-' || extract(epoch from now())::bigint, updated_at=NOW()
  WHERE id IN (SELECT id FROM candidates)
  RETURNING id, slug, project_id, prompt, base_branch, kind, attempt, force_coder, account
)
SELECT c.*, p.name AS project_name, p.repo_path, p.default_base
FROM claimed c JOIN projects p ON c.project_id = p.id;
```

If 0 rows → heartbeat (Step 4), write `<run-summary>`, stop. **This is the ONLY exit condition.**

---

## Step 2: REPO SETUP (once per unique repo per loop)

```bash
cd {repo_path}
git fetch origin --quiet 2>&1 | tail -2
# DO NOT rewrite origin. It is already correct and authenticated via osxkeychain.
# Injecting a token here (empty, since fleet_config no longer holds one) is what broke
# every push — for this executor AND for the runner sharing the same clone.
git remote -v | head -1
```

---

## Step 3: IMPLEMENT EACH TASK (all claimed tasks, sequentially, Claude-only)

### 3a. Quarantine gate — binary garbage ONLY
If prompt is a hex-only `PATCH TEMPLATE` stub with no readable English implementation intent:
```sql
UPDATE tasks SET state='QUARANTINED', note='v6.5: binary PATCH TEMPLATE stub' WHERE id='{id}';
```
Move to next task. This is the ONLY quarantine reason.

### 3a-pre. LOOK ON ORIGIN BEFORE YOU BUILD (mandatory)

A requeued task very often already has finished work pushed under its own slug. Rebuilding
it is the single largest source of wasted fleet capacity.

```bash
cd {repo_path}
git fetch origin --quiet
EXISTING=$(git ls-remote --heads origin "agent/{slug}" | awk '{print $1}')
if [ -n "$EXISTING" ]; then
  # Diff the COMMIT, not the branch. A branch cut from a stale base shows the commits
  # that landed on the base since as false "deletions" -- one such branch appeared to
  # delete 9,160 lines of tests when its actual commit was purely additive.
  git diff --stat "$EXISTING^" "$EXISTING"
fi
```

If `$EXISTING` is set and its commit is real, non-stub work: do NOT re-implement. Verify it
(merge it onto the base, run the touched tests), then record `artifact_commit=$EXISTING` and
`artifact_branch=agent/{slug}` and resolve the task. Re-implementing verified work already on
origin is a defect, not zero-skip diligence.

### 3b. Isolated worktree (NEVER checkout branches in the main repo)
```bash
cd {repo_path}
git worktree prune 2>&1
WT="$(dirname {repo_path})/$(basename {repo_path})-wt/{slug}"
git worktree add --force "$WT" -B agent/{slug} origin/{base_branch} 2>&1   || git worktree add --force "$WT" -B agent/{slug} {base_branch} 2>&1   || git worktree add --force "$WT" -B agent/{slug} 2>&1
cd "$WT"
```
Do NOT run `git stash` or `git checkout` in `{repo_path}` — ever. If worktree creation fails because the branch is checked out in a stale worktree, run `git worktree prune` then retry. If locked, unlock first.

### 3c. Fetch pre-optimized enrichment (runner.py pre-work)
```bash
python3 /Users/kpasch/Documents/beethoven/claude-orchestrator/runner/cowork_assemble.py   --task-id "{id}" --slug "{slug}" --kind "{kind}" --attempt {attempt}   --repo-path "{repo_path}" --project-id "{project_id}"   --project-name "{project_name}" 2>/dev/null
```
Use `enriched_prompt` if non-empty. Fall back to raw `prompt` if it fails. Never skip because enrichment failed.

### 3d. IMPLEMENT with Claude

Read the enriched_prompt (or raw prompt). Use `read_file` to understand existing code patterns, then `write_file`/`edit_block` to write the implementation.

**All task types — Claude ships real code:**
- **recovery / missing-branch** → Check for existing branch first. Implement the recovery or reconstruct the patch.
- **toolchain-repair** → Run the failing command via `start_process`, fix what it reports.
- **bugfix / qafix / relfix** → Minimal targeted fix. If tests already pass and the described bug demonstrably does not exist: mark the task SUPERSEDED with a note explaining why — NO stub commit, NO verification doc.
- **build / feature / canary** → Implement as described. Read existing patterns for conventions.
- **improve-* / high-level** → Find ONE concrete bottleneck in the relevant file, implement the improvement.
- **"secret" / "legal" / "sensitive" / "vague"** → Category labels only. Implement the code change described. If no code target: create `docs/{slug}-analysis.md` and commit it.
- **Truly ambiguous** → Read `{repo_path}/CLAUDE.md`, grep for slug keywords, find the most relevant file, make a meaningful targeted improvement.

**Rule: prefer a real code change. If nothing real can be committed, mark the task BLOCKED with a note naming what is missing — never fabricate a stub commit.**

### 3e. Commit (inside the worktree, not the main repo)
```bash
cd "$WT"
git add -A
git diff --cached --stat
git -c user.name="Kale Pasch" -c user.email="kalepasch@gmail.com" commit --no-verify -m "agent: {slug}" 2>&1
```
If `nothing to commit` → do NOT fabricate a stub commit. Mark the task BLOCKED with a note naming exactly what is missing (e.g. 'no code target found for {slug}: looked in <files>'), remove the worktree, and move to the next task.

### 3f. Push, then remove the worktree (branch survives)
```bash
git push origin HEAD:agent/{slug} --force 2>&1 | tail -3

# Capture the evidence BEFORE leaving the worktree. A DONE row without a SHA is
# unverifiable, gets reverted by the next audit, and the task is rebuilt from scratch.
PUSHED_SHA=$(git rev-parse HEAD)
git ls-remote --heads origin "agent/{slug}" | grep -q "$PUSHED_SHA" || echo "WARN: origin does not report $PUSHED_SHA — do NOT mark DONE"
cd {repo_path} && git worktree remove --force "$WT" 2>&1 || true
```
Push failure → do NOT mark DONE. Retry the push once; if it still fails, leave the task RUNNING for a same-session retry or mark it BLOCKED with the push error in the note — a task is only DONE when its branch is actually on origin. Always remove the worktree.

### 3g. Mark DONE + heartbeat remaining claims

**DONE gate: mark DONE ONLY when (a) `git push origin HEAD:agent/{slug}` succeeded, AND (b) the committed diff contains non-doc code changes (or the task is genuinely a documentation task). Anything else → BLOCKED / SUPERSEDED per the rules above.**
```sql
UPDATE tasks SET state='DONE',
  artifact_commit='{pushed_sha}',   -- REQUIRED: the SHA captured in 3f
  artifact_branch='agent/{slug}',   -- REQUIRED: where that SHA lives on origin
  note='cowork-executor-v6.5: implemented and pushed (isolated worktree)'
WHERE id='{id}';
UPDATE tasks SET updated_at=now()
WHERE state='RUNNING' AND account='{my_account}';
```

**→ Start next task immediately. No pausing. No summaries between tasks.**

---

## Step 3.5: RELEASE QUEUE ONLY

Never call the Vercel CLI from a task or batch. Push only the agent branch. The
merge train and release train batch production changes; Vercel's Git integration
deploys only the configured production branch.

---

## Step 4: HEARTBEAT + LOOP

```sql
INSERT INTO fleet_config (key,value)
VALUES ('COWORK_EXECUTOR_V6_LAST_RUN',
  '{"ts":"{iso_now}","claimed":{total_claimed},"done":{total_done}}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
```

**→ IMMEDIATELY go back to Step 0b (release zombies) and Step 1 (claim next batch). Do NOT write `<run-summary>`. Do NOT pause. Do NOT summarize. Just loop.**

The ONLY time you stop and write `<run-summary>` is when Step 1 returns 0 rows (queue empty).

---

## Hard Rules

1. Never push to `main`/`dev`/`master` — only `agent/{slug}` branches.
2. Never `DROP TABLE` / `TRUNCATE` without WHERE on production tables.
3. **Valid BLOCK reasons**: repo path does not exist, nothing real to commit (no code target — name what is missing in the note), or push failure after retry (include the push error in the note).
4. **ONLY valid QUARANTINE reason**: binary hex-only PATCH TEMPLATE with no readable English.
5. **"Tests already pass / already done / no fix needed"** → mark **SUPERSEDED** with a note explaining why; never commit a stub or verification doc.
6. **"Sensitive / legal / vague / secret"** → not a skip — implement via 3d.
7. Re-queue only if an actively-required live external service is unavailable.
8. **NEVER stop after completing a batch if there might be more work. ALWAYS loop back and try to claim.**

## What Is Never Acceptable
- `<run-summary>` before the queue is empty
- Leaving any task RUNNING without resolving to DONE/QUARANTINED/BLOCKED
- "Skipped N tasks" — zero skips
- BLOCKED without a note naming exactly what is missing or failing
- Any direct Vercel deploy — production is release-train-only
- Stopping after one batch when more tasks exist
- Writing prose summaries between batches — just loop
