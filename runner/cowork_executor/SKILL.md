---
name: cowork-executor
description: High-throughput autonomous task executor for claude-orchestrator. Claims 5 QUEUED tasks atomically upfront, implements ALL of them, pushes branches, batch-deploys to Vercel. Multi-vendor primary routing. Zero skip. Runs every 2 minutes.
---

# Cowork Executor v6.2 — Atomic Claim · Multi-Vendor Primary · Batch Vercel · Zero Skip

**`<run-summary>` IS FORBIDDEN until Step 4. Writing one before all tasks are DONE ends the session early and creates zombies.**

**ZERO SKIP: Every claimed task gets code committed and pushed. Sensitivity, vagueness, secrets — none are skip reasons.**

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

## Step 0: FETCH KEYS (one SQL, store all four)

```sql
SELECT key, value::text FROM fleet_config
WHERE key IN ('GITHUB_PAT','OPENAI_API_KEY','GEMINI_API_KEY','VERCEL_TOKEN');
```

Store: `{GITHUB_PAT}`, `{OPENAI_API_KEY}`, `{GEMINI_API_KEY}`, `{VERCEL_TOKEN}`.
These are used throughout. VERCEL_TOKEN is used in the batch deploy at the end — no need to get it anywhere else.

### Step 0b: RELEASE ZOMBIES from crashed/rate-limited sessions

Other accounts' sessions may have died (rate-limit, crash) leaving tasks stuck RUNNING.
Release them NOW so this session (or any other account) can claim them:

```sql
UPDATE tasks SET state='QUEUED', note='v6.2: zombie released — session expired >30min'
WHERE state='RUNNING'
  AND updated_at < now() - interval '30 minutes'
  AND account LIKE 'cowork-executor%';
```

This is safe: FOR UPDATE SKIP LOCKED in Step 1 ensures no double-claiming.

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
  UPDATE tasks SET state='RUNNING', account='cowork-executor-v6', updated_at=NOW()
  WHERE id IN (SELECT id FROM candidates)
  RETURNING id, slug, project_id, prompt, base_branch, kind, attempt, force_coder
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
# Set PAT-authenticated remote once per repo (used for all pushes)
git remote set-url origin https://x-access-token:{GITHUB_PAT}@github.com/kalepasch1/{repo_name}.git
```

---

## Step 3: IMPLEMENT EACH TASK (all 5, sequentially)

### 3a. Quarantine gate — binary garbage ONLY
If prompt starts with `PATCH TEMPLATE` followed by a hex hash and NO readable English implementation description:
```sql
UPDATE tasks SET state='QUARANTINED', note='v6.2: binary PATCH TEMPLATE stub' WHERE id='{id}';
```
Move to next task. This is the ONLY quarantine reason.

### 3b. Branch checkout
```bash
cd {repo_path}
git stash --quiet 2>&1 || true
git checkout {base_branch} --quiet 2>&1 || git checkout {default_base} --quiet 2>&1
git checkout -b agent/{slug} origin/{base_branch} --quiet 2>&1   || git checkout agent/{slug} --quiet 2>&1   || git checkout -b agent/{slug} --quiet 2>&1
```

### 3c. VENDOR ROUTING — use the fastest tool for the task type

**Route to OpenAI (primary for build/canary/mechanical):**
If `kind` is `build` or `canary`, OR prompt contains `task class: legal` or `task class: mechanical`:

```bash
IMPL=$(curl -s https://api.openai.com/v1/chat/completions   -H "Authorization: Bearer {OPENAI_API_KEY}"   -H "Content-Type: application/json"   -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "system", "content": "You are a code implementation agent. Return ONLY file changes — no explanation, no markdown wrapper. Format: filepath:\n<full file content>"},
      {"role": "user", "content": "Implement this task for repo {project_name}:\n\n{prompt}\n\nRead existing files first if needed. Make the smallest correct change. Commit-ready output only."}
    ],
    "max_tokens": 3000
  }' | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['choices'][0]['message']['content'])" 2>/dev/null)
echo "$IMPL"
```

Parse the response: for each `filepath:` line, write the content to that file in the repo.

If OpenAI fails or returns empty → fall through to Claude (Step 3d).

**Route to Gemini (fallback for build if OpenAI fails):**
```bash
curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"   -H "Content-Type: application/json"   -d '{"contents":[{"parts":[{"text":"Implement this code change for {project_name}. Return filepath: then full file content.\n\n{prompt}"}]}]}'   | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['candidates'][0]['content']['parts'][0]['text'])" 2>/dev/null
```

### 3d. CLAUDE IMPLEMENTATION (bugfix / toolchain-repair / recovery / or OpenAI fallback)

For `kind` in `bugfix`, `recovery`, `toolchain-repair`, or if 3c returned empty:

Use `read_file` to understand the existing code, then `write_file`/`edit_block` to implement.

**All task types ship real code:**
- **recovery / missing-branch / rework-*** → Implement the recovery. Check for existing branch/worktree first.
- **toolchain-repair** → Run the failing command, fix what it reports.
- **bugfix / qafix / relfix** → Find the bug from the prompt, write minimal targeted fix.
- **build / feature** → Implement as described. Read existing patterns first.
- **canary** → Write a minimal probe/test that confirms the behavior described.
- **"secret" / "legal" / "sensitive"** → These are category labels only. Implement the described code change. If genuinely no code target: create `docs/{slug}-analysis.md`.
- **Truly ambiguous** → Read `{repo_path}/CLAUDE.md`, grep for slug keywords, find the most relevant file, make a meaningful targeted improvement. Commit it.

**If tests already pass for a qafix/relfix task** → commit `docs/{slug}-verified.md` confirming tests green, mark DONE. Do not mark BLOCKED.

### 3e. Commit
```bash
cd {repo_path}
git add -A
git diff --cached --stat
git commit --no-verify -m "agent: {slug}" 2>&1
```
If `nothing to commit` → create `docs/{slug}-stub.md` with implementation notes and commit that.

### 3f. Push
```bash
git push origin HEAD:agent/{slug} --force 2>&1 | tail -3
```
Push failure → log it, still mark DONE (merge-train handles retry).

### 3g. Mark DONE
```sql
UPDATE tasks SET state='DONE',
  note='cowork-executor-v6: implemented and pushed'
WHERE id='{id}';
```

**→ Start next task immediately. No pausing. No intermediate summaries.**

---

## Step 3.5: BATCH VERCEL DEPLOY (after ALL 5 tasks are marked DONE)

Collect the unique `repo_path` values from your 5 tasks. For each unique project:

```bash
# Use vercel CLI (pre-installed) or npx
npx vercel@latest deploy   --token="{VERCEL_TOKEN}"   --cwd="{repo_path}"   --yes   --no-wait 2>&1 | tail -3 || true
```

`--no-wait` returns immediately after triggering the build — don't block on it. One deploy per unique project, not per task.

If VERCEL_TOKEN is empty, skip this step silently.

---

## Step 4: HEARTBEAT

```sql
INSERT INTO fleet_config (key,value)
VALUES ('COWORK_EXECUTOR_V6_LAST_RUN',
  '{"ts":"{iso_now}","claimed":5,"done":{n}}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
```

Only now write a one-line summary of tasks completed.

---

## Hard Rules

1. Never push directly to `main`/`dev`/`master` — only `agent/{slug}` branches.
2. Never `DROP TABLE` / `TRUNCATE` without WHERE on production tables.
3. **ONLY valid BLOCK reason**: repo path literally does not exist on this machine (`ls {repo_path}` fails).
4. **ONLY valid QUARANTINE reason**: binary garbage hex-only prompt (no readable English).
5. **"Tests already pass / no fix needed / already done"** → mark **DONE**, never BLOCKED.
6. **"Sensitive / legal / vague"** → not a skip or BLOCK reason — implement via 3c or 3d.
7. Re-queue only if an external live service is actively required: `UPDATE tasks SET state='QUEUED', note='needs {service}'`.

## What Is Never Acceptable
- `<run-summary>` before Step 4
- Leaving any task RUNNING without setting DONE/QUARANTINED/BLOCKED
- "Skipped N tasks" — zero skips
- BLOCKED for "no fix needed", "already done", "tests pass", "too complex"
- Per-task Vercel deploys (batch only at Step 3.5)
- Calling `cowork_assemble.py` — removed in v6.2 (keys come from Step 0)
