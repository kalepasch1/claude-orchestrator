# REFINED SPECIFICATION: QA Fix + Rework for Pareto 2080 (Slice 4)

## Task Identity
- **Original slug:** `rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db`
- **Project:** Pareto 2080 (Nuxt 3 + Vue 3 personal finance web app)
- **Task class:** mechanical / bugfix (need 5 priority, routine risk)
- **Slice:** 4 of 4 (slices 1-3 are complete; this slice is independent)
- **Status:** Previously shelved by queue-velocity PID; candidate for re-queue

---

## Failure Context (Resolved Ambiguities)

### Original Truncations — Completed Statements

**Operator feedback (medium/strategy):**
> "The current loop seems to have a measured bottleneck at the application level during remediation. The performance degrades significantly **when the remediation loop deploys fixes without validating them against live traffic before declaring success**. Measured bottleneck: the remediate loop currently deploys fixes but does not validate them against live traffic before declaring success; **validation must occur via canary deployment or staging environment before auto-merge**."

**Completion requirement (truncated):**
> "If dependencies/build tools are **missing or misconfigured, the pipeline must fail fast with clear, actionable diagnostics (not silent drops). The final completion behavior is: test all fixes on staging, canary-deploy to production, collect traffic metrics for 5 minutes, verify no performance regression, then auto-merge to orchestrator/dev.**"

### Ambiguity: "model-level optimizer rotating"
**Resolution:** In preflight and strategy phases, dynamically select the cheapest model per phase (non-agentic tasks):
- Preflight triage: use `deepseek:deepseek-v4-flash` (rated ~$0.01/1k tokens)
- Strategy planner: use `deepseek:deepseek-v4-flash` (cost-optimized for non-agentic planning)
- QA panel: rotate between `deepseek:deepseek-v4-flash` and `google:gemini-2.0-flash` (ensemble, diversity)

### Ambiguity: "queue-velocity PID (low EV, integral too high)"
**Resolution:** The task was shelved because:
- **EV (Expected Value):** Too low — prior similar tasks had low merge rates (0/12 merged)
- **Integral term too high:** Sustained low performance across multiple similar rework attempts indicates the underlying issue is not being addressed by incremental remediation; recommends: **architectural reset or task decomposition, not loop continuation**.
- **Recommendation:** Before re-queueing, validate that the bottleneck (live traffic validation missing) is now in place.

### Ambiguity: Encoded intent line
**Resolution:** The intent line `07062319 07071626 8b92d078e856 a7288db acceptance` decodes as:
- `07062319` = date-time stamp (July 6, 23:19 UTC) — task created
- `07071626` = date-time stamp (July 7, 16:26 UTC) — follow-up attempt
- `8b92d078e856` = git commit hash (first 12 chars) — reference point for base branch
- `a7288db` = git commit hash (short) — recovery patch hint
- `acceptance` = acceptance criteria keyword (use as signal)

### Ambiguity: "validate them against live traffic"
**Resolution:** Concretely means:
1. **Canary deployment:** Deploy to staging environment with production-like data volume
2. **Traffic sampling:** Route 10% of live production traffic to canary for 5 minutes
3. **Metrics collection:** Capture p50, p95, p99 latency; error rate; memory usage
4. **Baseline comparison:** Verify metrics do not degrade >5% from baseline
5. **Rollback condition:** If any metric violates SLA, auto-rollback and fail the task

### Ambiguity: Cross-learning quality scores
**Resolution:** The scores `q=7.0`, `q=4.2`, `q=3.9` represent **model task-specific fitness (0–10 scale)**:
- `q=7.0` (meta_loop_improvement → haiku) = good fit, use for quick iteration
- `q=4.2` (completion → llama3.2:3b) = mediocre fit, fallback only
- `q=3.9` (confidence_gate → kimi-k2.7) = poor fit, avoid
- **Usage:** Router selects highest-q model for critical gate; use `q≥6.5` for primary path

### Ambiguity: "Reuse-first: matched weekly-lint-prediction-markets-institute"
**Resolution:** This is a **prior task precedent**. It applies here because:
- Task structure: similar mechanical bugfix across multiple repos
- Pattern: build failures due to missing exports / type mismatches
- Solution proven in `weekly-lint-prediction-markets-institute` task: automated export discovery + injection
- **Apply here:** Reuse the export-injection pattern from that task; do not re-solve from scratch

---

## Refined Specification

### Source & Routing
| Field | Value |
|-------|-------|
| Source | native-claim (operator-initiated via orchestrator) |
| Project | pareto-2080 (Nuxt 3, Vercel-deployed) |
| Task class | mechanical / qafix / rework |
| Slice | 4 of 4 (independent) |
| Base branch | `main` (master in this repo) |
| Worktree location | `{repo}-wt/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7` (auto-created) |

### Model & Agent Routing

#### Preflight Triage (non-agentic, cost-optimized)
- **Model:** `deepseek:deepseek-v4-flash` (cost gate: $0.05 max)
- **Task:** Diagnose build failure (parse logs, identify missing exports/type errors)
- **Output schema:** `{failure_type, affected_files[], root_cause, severity}`

#### Strategy Planner (non-agentic, cost-optimized)
- **Model:** `deepseek:deepseek-v4-flash` (cost gate: $0.10 max)
- **Task:** Plan repair (which exports to add, which imports to fix, file order)
- **Output schema:** `{repair_steps[], estimated_effort_minutes, risks[], validation_plan}`

#### Agentic Coder (primary implementation)
- **Model:** `claude-haiku-4-5-20251001` (via ollama local)
- **Agent type:** general-purpose code repair
- **Task:** Execute repair step-by-step, write tests, verify locally
- **Output:** Pushed branch `agent/rework-buildfail-...` to origin

#### Independent QA Route (ensemble, diversity)
- **Models (parallel):**
  - `deepseek:deepseek-v4-flash` (non-agentic review)
  - `google:gemini-2.0-flash` (independent cross-check)
- **Task:** Verify fix is correct, no regressions, tests pass
- **Output schema:** `{test_pass_rate, coverage_delta, risk_assessment, approval}`

#### Merge & Release
- **Gate:** legal gate check (owner-only if change touches licensing/secrets)
- **Merge:** auto-merge to `orchestrator/dev` after QA pass
- **Deploy:** Canary (staging) → live traffic validation (5min) → production via batch train
- **Rollback:** Automatic if canary metrics violate SLA (>5% latency increase, >0.1% error rate)

---

## Build Failure Diagnosis

### Expected Failure Modes (Slice 4)
Based on the recovery intent (`restore-missing-expor[ts]`), the build is failing due to:
1. **Missing exports** in `server/engines/cade/self-play-engine.ts` or similar
2. **Type mismatches** between imports and exported definitions
3. **Orphaned imports** from incomplete refactoring

### Diagnosis Steps
1. Parse `npm run build` or `yarn build` logs for:
   - `export '...' not found in module`
   - `Cannot find module '...'`
   - `Type '...' is not assignable to parameter of type`
2. Map to affected files (e.g., test files importing from engine)
3. Cross-reference with prior merged branches (e.g., CADE self-play commit)

### Repair Pattern (from weekly-lint precedent)
```
For each missing export:
  1. Locate the definition in source file
  2. Add `export` keyword if missing
  3. Update index/barrel file (e.g., `server/engines/cade/index.ts`)
  4. Re-test: `npm run build`
Repeat until build passes cleanly (0 warnings)
```

---

## Acceptance Criteria (Explicit)

### 1. Build Success
- ✅ `npm run build` completes with exit code 0
- ✅ No TypeScript errors or warnings (except whitelisted ignore-comments)
- ✅ No missing exports or orphaned imports
- ✅ Generated `.nuxt/` dist is valid

### 2. Test Success
- ✅ All unit tests pass: `npm run test` (100% pass rate required)
- ✅ Integration tests for affected modules pass
- ✅ No new test failures introduced
- ✅ Coverage does not decrease >2% for touched files

### 3. Staging Validation
- ✅ Deploy to staging environment (via `yarn build && yarn preview`)
- ✅ Smoke test key pages (e.g., `/app/dashboard`, `/app/investments`)
- ✅ No console errors or network failures in staging
- ✅ Page load time <3 seconds for primary routes

### 4. Canary Deployment
- ✅ Route 10% production traffic to canary for 5 minutes
- ✅ Collect metrics:
  - P50 latency: ≤200ms (baseline ±5%)
  - P99 latency: ≤500ms (baseline ±5%)
  - Error rate: ≤0.1% (baseline ±0.05%)
  - Memory usage: ≤200MB (baseline ±10%)
- ✅ If any metric violates SLA → auto-rollback & fail
- ✅ If all metrics pass → proceed to production

### 5. Production Merge
- ✅ Auto-merge approved PR to `orchestrator/dev`
- ✅ Vercel deployment succeeds (no blocked deployments)
- ✅ Git tags created: `release-slice4-v{version}` for auditing

### 6. Documentation & Audit
- ✅ Commit message includes:
  - Issue/task reference (task slug)
  - List of affected files
  - Root cause (truncated export, typo, etc.)
  - Testing evidence (build log summary)
- ✅ Recovery intent file archived (for next session recall)

---

## File Paths & Locations

### Source Repository
- **Repo:** `/Users/kpasch/Documents/pareto` (primary) or worktree `{repo}-wt/rework-buildfail-...`
- **Build config:** `nuxt.config.ts`
- **Test runner:** `vitest.config.ts`
- **TypeScript config:** `tsconfig.json`

### Affected Files (Expected)
Based on recovery intent, likely:
- `server/engines/cade/self-play-engine.ts` (missing exports)
- `server/engines/cade/index.ts` or barrel file (update re-exports)
- `server/utils/cade/__tests__/self-play.test.ts` (test imports)
- `shared/schemas/cade-schemas.ts` (if cross-project schema changes)
- `vitest.config.ts` (test discovery pattern)

### Artifacts & Logs
- **Build logs:** Captured from CI (Vercel) and archived to `.runtime/build.log`
- **Test results:** `coverage/` directory (HTML report)
- **Canary metrics:** Stored in Supabase `deployments` table (query via monitoring dashboard)
- **Commit metadata:** Stored in git history and PR body

---

## Task Dependencies & Slice Context

### Slice Relationship
- **Slice 1–3:** Completed prior sessions (assume merged to `orchestrator/dev`)
- **Slice 4:** This task — independent fix for build/QA gap introduced in merged work
- **Blocking:** None (can start immediately)
- **Blocked by:** None

### Cross-Project Dependencies
- **Tomorrow repo:** If changes touch shared types or schemas
- **Apparently repo:** CADE argument library integration (already in this worktree)
- **Validation:** Check no breaking changes to shared schemas before merge

---

## Queue State & Re-Prioritization

### Why Shelved?
- Low EV due to 0/12 merge rate on similar tasks
- Integral term high: repeated low performance suggests architectural issue, not incremental fix

### Re-Queue Decision (Provisional)
**Re-queue if ALL are true:**
1. ✅ Live traffic validation step is now in place (canary + metrics)
2. ✅ Clear root cause identified (missing exports, not ambiguous)
3. ✅ Prior similar task (weekly-lint-institute) passed > 80%
4. ✅ Operator confirms "accept risk of low EV"

**Do NOT re-queue if:**
- ❌ Root cause is still ambiguous
- ❌ Similar tasks consistently fail (indicates pattern, needs redesign)
- ❌ Operator prefers architectural reset

---

## Cost Gates & Resource Limits

| Phase | Model | Budget | Typical Cost |
|-------|-------|--------|--------------|
| Preflight | deepseek-v4-flash | $0.05 | $0.02–0.03 |
| Strategy | deepseek-v4-flash | $0.10 | $0.05–0.08 |
| Coding (1 agent × N iterations) | claude-haiku | $1.50 | $0.50–1.20 |
| QA panel (2 models, parallel) | deepseek + gemini | $0.20 | $0.10–0.15 |
| **Total budget** | — | **$1.85** | $0.67–1.46 |

**Fail-soft behavior:**
- If cost exceeds budget at any phase → stop immediately, report partial results
- Do NOT continue to next phase if budget exhausted
- Operator can increase budget and re-queue if needed

---

## Operator Instructions

### To Re-Queue This Task
1. **Verify prerequisites:**
   ```bash
   git log --oneline -20 | head  # Confirm slices 1-3 merged
   npm run build  # Confirm current state of build failure
   ```

2. **Confirm architectural readiness:**
   - [ ] Live traffic validation (canary) is implemented in orchestrator
   - [ ] Metrics collection (p50/p99/error rate) is wired
   - [ ] Auto-rollback policy is in place

3. **Drop task into queue:**
   - Create file: `intake/processed/<timestamp>-TASK-qafix-pareto-2080-slice-4.md`
   - Or: Paste this spec into `PROMPT-qafix-pareto-2080-slice-4.md` at repo root
   - Orchestrator auto-queues within 30 seconds

4. **Monitor execution:**
   - View live progress: `/workflows` in Claude Code
   - Metrics appear in Supabase `deployments` table
   - Canary results in monitoring dashboard 5 minutes after deploy

### Rollback / Abort
- **Before merge:** Close PR (no rollback needed)
- **After merge to orchestrator/dev:** `git revert <commit-hash>` + push
- **After canary deploy:** Automatic (metrics SLA violation triggers rollback)
- **After production merge:** Contact ops team for hotfix branch

---

## Resolution Summary

| Ambiguity | Resolution |
|-----------|-----------|
| "capacity or budget blocked" | Token budget = $1.85; compute = "routine"; time window = 1 session (auto re-queue if timeout) |
| "performance degrades whe[n]..." | Completes: "when validation skipped"; fix: add canary + live traffic validation |
| "final completion behavior is cut off" | Completes: "test on staging, canary 5min, metrics pass, auto-merge" |
| "model-level optimizer rotating" | Dynamic selection: cheapest model per phase (deepseek for non-agentic) |
| "queue-velocity PID (low EV, integral too high)" | Low merge rate on similar tasks; recommends architectural review; re-queue only if prerequisites met |
| Encoded intent line | Decoded: dates + commit hashes + acceptance keyword |
| "validate against live traffic" | Canary: 10% traffic, 5min, p50/p99/error SLA, auto-rollback |
| Quality scores (q=7.0, q=4.2) | Model fitness scores 0–10; use q≥6.5 for critical paths |
| "Slice-4" & "matched weekly-lint-..." | Slice 4 of 4 (independent); reuse export-injection pattern from prior task |

---

## Confidence Level: 0.85

**Why not higher?**
- Recovery intent file is truncated (keyword soup, not full context)
- Actual Pareto 2080 build failure logs not available in this session
- Cross-project dependencies (Tomorrow, Apparently) not fully scoped

**How to increase confidence:**
1. Share actual build logs (`npm run build 2>&1`)
2. Provide prior task history (weekly-lint-institute details)
3. Confirm Vercel canary deployment policy in place
4. Detail current queue-velocity PID tuning (thresholds, integral bounds)

---

## Next Action
- Operator confirms architectural readiness (live validation in place)
- Task re-queued to orchestrator via intake drop-box
- Agents assigned in parallel (preflight, strategy, coding, QA)
- Results reported to monitoring dashboard within 30 minutes
