---
name: cowork-executor
description: High-throughput autonomous task executor for claude-orchestrator. Claims 5 QUEUED tasks atomically, reads pre-optimized enriched prompts, implements ALL with Claude, pushes branches, batch-deploys Vercel. Zero skip. Runs every 2 minutes.
---

# Cowork Executor v6.4 — Claude-Only Implementation · Enriched Prompts · Batch Vercel · Zero Skip

**`<run-summary>` IS FORBIDDEN until Step 4. Writing one before all tasks are DONE ends the session early and creates zombies.**

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

## Step 0: FETCH KEYS + RELEASE ZOMBIES

### 0a. Credentials — DO NOT FETCH ANY
This machine already holds working credentials; fetching them is both unnecessary and
forbidden. `git` authenticates through the `osxkeychain` credential helper against each
repo's existing clean origin URL, and the `vercel` CLI is already logged in.

NEVER read GITHUB_PAT / VERCEL_TOKEN / API keys from `fleet_config`, and NEVER write them
there. Those rows were purged in the 2026-08-02 plaintext-credential incident and a DB
guard now rejects them, so any such SELECT returns nothing — which silently produced an
empty token, a broken origin URL, and a failed push on every run of all 16 executors.
Use the ambient credentials as-is.

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

If 0 rows → heartbeat (Step 4), stop.

---

## Step 2: REPO SETUP (once per unique repo)

```bash
cd {repo_path}
git fetch origin --quiet 2>&1 | tail -2
# DO NOT rewrite origin. It is already correct and authenticated via osxkeychain.
# Injecting a token here (empty, since fleet_config no longer holds one) is what broke
# every push — for this executor AND for the runner sharing the same clone.
git remote -v | head -1
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
cd {repo_path} && git worktree remove --force "$WT" 2>&1 || true
```
Push failure → do NOT mark DONE. Retry the push once; if it still fails, leave the task RUNNING for a same-session retry or mark it BLOCKED with the push error in the note — a task is only DONE when its branch is actually on origin. Always remove the worktree so `-wt` dirs don't accumulate; the local agent branch keeps the work.

### 3g. Mark DONE + heartbeat remaining claims

**DONE gate: mark DONE ONLY when (a) `git push origin HEAD:agent/{slug}` succeeded, AND (b) the committed diff contains non-doc code changes (or the task is genuinely a documentation task). Anything else → BLOCKED / SUPERSEDED per the rules above.**
```sql
UPDATE tasks SET state='DONE',
  note='cowork-executor-v6.4: implemented and pushed (isolated worktree)'
WHERE id='{id}';
-- Heartbeat: keep this session's other claimed tasks out of the zombie sweep
UPDATE tasks SET updated_at=now()
WHERE state='RUNNING' AND account='{my_account}';
```
(`{my_account}` = the `account` value returned by the Step 1 claim — note it when you claim.)

**→ Start next task immediately. No pausing. No summaries.**

---

## Step 3.5: BATCH VERCEL DEPLOY (after ALL 5 tasks are marked DONE)

For each unique `repo_path` from your 5 tasks, deploy once:
```bash
npx vercel@latest deploy   --cwd="{repo_path}"   --yes   --no-wait 2>&1 | tail -3 || true
```
`--no-wait` returns immediately. One deploy per unique project, not per task.
The CLI is already authenticated (`vercel whoami`); pass NO --token. If the CLI
reports it is logged out, report that in the heartbeat rather than guessing a token.

---

## Step 4: HEARTBEAT

```sql
INSERT INTO fleet_config (key,value)
VALUES ('COWORK_EXECUTOR_V6_LAST_RUN',
  '{"ts":"{iso_now}","claimed":5,"done":{n}}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
```

Only now write a one-line summary.

---

## Hard Rules

1. Never push to `main`/`dev`/`master` — only `agent/{slug}` branches.
2. Never `DROP TABLE` / `TRUNCATE` without WHERE on production tables.
3. **Valid BLOCK reasons**: repo path does not exist, nothing real to commit (no code target — name what is missing in the note), or push failure after retry (include the push error in the note).
4. **ONLY valid QUARANTINE reason**: binary hex-only PATCH TEMPLATE with no readable English.
5. **"Tests already pass / already done / no fix needed"** → mark **SUPERSEDED** with a note explaining why; never commit a stub or verification doc.
6. **"Sensitive / legal / vague / secret"** → not a skip — implement via 3d.
7. Re-queue only if an actively-required live external service is unavailable.

## What Is Never Acceptable
- `<run-summary>` before Step 4
- Leaving any task RUNNING without resolving to DONE/QUARANTINED/BLOCKED
- "Skipped N tasks" — zero skips
- BLOCKED without a note naming exactly what is missing or failing
- Per-task Vercel deploys — batch only at Step 3.5
- Using OpenAI/Gemini for code implementation in this session — that happens upstream in runner.py, not here
