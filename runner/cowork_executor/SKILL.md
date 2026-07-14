---
name: cowork-executor
description: High-throughput autonomous task executor for claude-orchestrator. Claims 5 QUEUED tasks atomically, reads pre-optimized enriched prompts, implements ALL with Claude, pushes branches, batch-deploys Vercel. Zero skip. CONTINUOUS LOOP — never stops until queue is empty.
---

# Cowork Executor v6.4 — Claude-Only Implementation · Enriched Prompts · Batch Vercel · Zero Skip

**`<run-summary>` IS FORBIDDEN until Step 4. Writing one before all tasks are DONE ends the session early and creates zombies.**

**ZERO SKIP: Every claimed task gets code committed and pushed. Sensitivity, vagueness, secrets — none are skip reasons.**

**CONTINUOUS LOOP: After completing a batch of 5 and deploying, immediately claim the next 5. Only stop when the queue returns 0 rows. Never pause between batches. Never wait for a human prompt.**

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

## Step 0: FETCH KEYS + RELEASE ZOMBIES

### 0a. Keys
```sql
SELECT key, value::text FROM fleet_config
WHERE key IN ('GITHUB_PAT','OPENAI_API_KEY','GEMINI_API_KEY','VERCEL_TOKEN');
```
Store: `{GITHUB_PAT}`, `{VERCEL_TOKEN}`. (Others available if needed.)

### 0b. Release zombies from crashed/rate-limited sessions
Any other executor account that hit a rate limit left tasks stuck RUNNING. Free them now so this session can claim them:
```sql
UPDATE tasks SET state='QUEUED', note='v6.4: zombie released — heartbeat stale >90min'
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
  FOR UPDATE SKIP LOCKED
),
claimed AS (
  UPDATE tasks SET state='RUNNING', account='cowork-executor-v6-' || extract(epoch from now())::bigint, updated_at=NOW()
  WHERE id IN (SELECT id FROM candidates)
  RETURNING id, slug, project_id, prompt, base_branch, kind, attempt, force_coder, account
)
SELECT c.*, p.name AS project_name, p.repo_path, p.default_base
FROM claimed c JOIN projects p ON c.project_id = p.id;
```

If 0 rows → heartbeat (Step 4), write `<run-summary>`, stop.

---

## Step 2: REPO SETUP (once per unique repo)

```bash
cd {repo_path}
git fetch origin --quiet 2>&1 | tail -2
git remote set-url origin https://x-access-token:{GITHUB_PAT}@github.com/kalepasch1/{repo_name}.git
```

---

## Step 3: IMPLEMENT EACH TASK (all 5, sequentially, Claude-only)

### 3a. Quarantine gate — binary garbage ONLY
If prompt is a hex-only `PATCH TEMPLATE` stub with no readable English implementation intent:
```sql
UPDATE tasks SET state='QUARANTINED', note='v6.4: binary PATCH TEMPLATE stub' WHERE id='{id}';
```
Move to next task. This is the ONLY quarantine reason.

### 3b. Isolated worktree (NEVER checkout branches in the main repo)
The main checkout is shared by other executors, the runner, and sentinel.py (which stashes+resets any non-base checkout it finds). All work happens in a per-task worktree instead — same `{repo}-wt/{slug}` convention the runner uses.

```bash
cd {repo_path}
git worktree prune 2>&1
WT="$(dirname {repo_path})/$(basename {repo_path})-wt/{slug}"
git worktree add --force "$WT" -B agent/{slug} origin/{base_branch} 2>&1   || git worktree add --force "$WT" -B agent/{slug} {base_branch} 2>&1   || git worktree add --force "$WT" -B agent/{slug} 2>&1
cd "$WT"
```
Do NOT run `git stash` or `git checkout` in `{repo_path}` — ever. If worktree creation fails because the branch is checked out in a stale worktree, run `git worktree prune` then retry.

### 3c. Fetch pre-optimized enrichment (runner.py pre-work)
The runner.py intelligence pipeline (prompt_assembler, reuse_first, queue_preopt) has already pre-processed this task. Retrieve it:

```bash
python3 /Users/kpasch/Documents/beethoven/claude-orchestrator/runner/cowork_assemble.py   --task-id "{id}" --slug "{slug}" --kind "{kind}" --attempt {attempt}   --repo-path "{repo_path}" --project-id "{project_id}"   --project-name "{project_name}" 2>/dev/null
```

Use `enriched_prompt` if non-empty (it contains pre-drafted implementation from upstream vendors). Fall back to raw `prompt` if the call fails or returns empty. Either way, proceed — never skip because enrichment failed.

### 3d. IMPLEMENT with Claude

Read the enriched_prompt (or raw prompt). Use `read_file` to understand existing code patterns, then `write_file`/`edit_block` to write the implementation.

The upstream vendors have already analyzed and pre-drafted this. Your job: apply the implementation cleanly, adapt it to the actual repo state, make it correct.

**All task types — Claude ships real code:**
- **recovery / missing-branch** → Check for existing branch first. Implement the recovery or reconstruct the patch.
- **toolchain-repair** → Run the failing command via `start_process`, fix what it reports.
- **bugfix / qafix / relfix** → Minimal targeted fix. If tests already pass: commit a verification doc, mark DONE.
- **build / feature / canary** → Implement as described. Read existing patterns for conventions.
- **improve-* / high-level** → Find ONE concrete bottleneck in the relevant file, implement the improvement.
- **"secret" / "legal" / "sensitive" / "vague"** → Category labels only. Implement the code change described. If no code target: create `docs/{slug}-analysis.md` and commit it.
- **Truly ambiguous** → Read `{repo_path}/CLAUDE.md`, grep for slug keywords, find the most relevant file, make a meaningful targeted improvement.

**Rule: something real must be committed. No exceptions.**

### 3e. Commit (inside the worktree, not the main repo)
```bash
cd "$WT"
git add -A
git diff --cached --stat
git -c user.name="Kale Pasch" -c user.email="kalepasch@gmail.com" commit --no-verify -m "agent: {slug}" 2>&1
```
If `nothing to commit` → create `docs/{slug}-stub.md` with implementation notes and commit that.

### 3f. Push, then remove the worktree (branch survives)
```bash
git push origin HEAD:agent/{slug} --force 2>&1 | tail -3
cd {repo_path} && git worktree remove --force "$WT" 2>&1 || true
```
Capture the committed SHA with `git rev-parse HEAD` before removing the worktree. A push is part of delivery: on push failure, mark the task `RETRY` with the concrete error and do **not** mark it `DONE`. Always remove the worktree so `-wt` dirs don't accumulate; a successfully pushed agent branch keeps the work.

### 3g. Mark DONE + heartbeat remaining claims
```sql
UPDATE tasks SET state='DONE',
  note='cowork-executor-v6.5: implemented, committed, and pushed (isolated worktree)',
  artifact_branch='agent/{slug}', artifact_commit='{committed_sha}'
WHERE id='{id}';
-- Heartbeat: keep this session's other claimed tasks out of the zombie sweep
UPDATE tasks SET updated_at=now()
WHERE state='RUNNING' AND account='{my_account}';
```
(`{my_account}` = the `account` value returned by the Step 1 claim — note it when you claim.)

`DONE` therefore means a remotely addressable artifact exists. Never write `DONE` when the
commit SHA is unknown, the branch is only local, or `git push` returned non-zero. Those cases stay
`RETRY`, which prevents the dashboard and integration sweeper from reporting undelivered work as
completed.

**→ Start next task immediately. No pausing. No summaries.**

---

## Step 3.5: RELEASE QUEUE ONLY

Do not call the Vercel CLI and do not create a deployment from an agent or dirty
worktree. The merge train batches completed branches into staging; the release
train is the only path that may push the configured production branch. Vercel's
Git integration then creates one production deployment for that batched push.

---

## Step 4: LOOP OR STOP

**IMMEDIATELY go back to Step 1 and claim another 5.** Only write `<run-summary>` and stop when Step 1 returns 0 rows.

When finally stopping (0 rows):
```sql
INSERT INTO fleet_config (key,value)
VALUES ('COWORK_EXECUTOR_V6_LAST_RUN',
  '{"ts":"{iso_now}","claimed":{total_claimed},"done":{total_done}}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
```

Only now write `<run-summary>` with totals across all batches.

---

## Hard Rules

- Never run `vercel deploy`, `vercel --prod`, or an equivalent `npx vercel`
  command from an agent worktree. Agent branches are build-free by policy.
- Never push directly to a production branch. Production changes flow through
  the merge train and release train so they can be batched and verified.

1. Never push to `main`/`dev`/`master` — only `agent/{slug}` branches.
2. Never `DROP TABLE` / `TRUNCATE` without WHERE on production tables.
3. **ONLY valid BLOCK reason**: repo path literally does not exist (`ls {repo_path}` fails).
4. **ONLY valid QUARANTINE reason**: binary hex-only PATCH TEMPLATE with no readable English.
5. **"Tests already pass / already done / no fix needed"** → mark **DONE**, never BLOCKED.
6. **"Sensitive / legal / vague / secret"** → not a skip — implement via 3d.
7. Re-queue only if an actively-required live external service is unavailable.
8. **NEVER STOP BETWEEN BATCHES.** After Step 3.5 deploy, go straight to Step 1. The session ends only when the queue is empty (0 rows from Step 1).

## What Is Never Acceptable
- `<run-summary>` before the queue is empty
- Leaving any task RUNNING without resolving to DONE/QUARANTINED/BLOCKED
- "Skipped N tasks" — zero skips
- BLOCKED for anything other than missing repo path
- Per-task Vercel deploys — batch only at Step 3.5
- Using OpenAI/Gemini for code implementation in this session — that happens upstream in runner.py, not here
- **Stopping after a batch when there are still QUEUED tasks** — this wastes the scheduled trigger and forces a 2-minute wait for the next run
- **Waiting for a human prompt between batches** — you are autonomous, loop until empty
