# Handoff v3.4 — state after finishing the twelve

All twelve v3.3 features are now wired, scheduled, and surfaced in the dashboard.

## What was done (this session)

### DB (migration 0005 — applied to live)
- `txns` table: cross-repo transaction tracking, RLS, realtime
- `tasks.confidence` column: stores per-task confidence score
- `projects.confidence_threshold`: override per project
- `projects.concurrency_weight`: set by daily ROI job

### Runner wiring
| # | Feature | What changed |
|---|---------|--------------|
| 1 | Spec-as-source-of-truth | `planner.py` reads SPEC.md via `--repo`; `periodic.py spec` runs weekly |
| 2 | Confidence-gated autonomy | `confidence.gate(threshold=proj_threshold)`; score stored in `tasks.confidence` and shown on dashboard |
| 3 | Blast-radius | `blast_radius.radius_after()` called before verify; dependents passed to `verify.review_diff(dependents=...)` so verifier checks coverage |
| 4 | Canary deploy | `deploy_window.py` + `periodic.py deploy` + nightly launchd plist |
| 5 | Mutation/property testing | `quality_gate.run()` called in `runner.py` after verify, before confidence gate |
| 6 | Preference learning | `opportunity_scout.py` calls `preference.should_suppress()` before filing proposals; predicted likelihood shown in detail |
| 7 | Cross-repo transactions | `periodic.py txn` (every 5 min) resolves pending txns + ff-merges all members when ready |
| 8 | Two-key approvals | Dashboard enforces in UI: first click sets `decided_by`, second click (different user) flips to `approved` + records `second_approver` |
| 9 | ROI scoring | Dashboard ROI panel; `periodic.py roi` (daily) updates `projects.concurrency_weight` |
| 10 | Deterministic replay | Dashboard runs table + Replay button → `/api/replay` → queues task `kind=replay`; `runner.py` handles it |
| 11 | NL analytics | `supabase/functions/ask/index.ts` edge function; dashboard search box calls it |
| 12 | Chaos drills | `periodic.py chaos` weekly (staging launchd); assertion step files result approval |

### New files
- `runner/deploy_window.py`
- `runner/periodic.py`
- `supabase/functions/ask/index.ts`
- `web/server/api/replay.post.ts`
- `scripts/launchd/com.claudeorchestrator.txn.plist` (5 min)
- `scripts/launchd/com.claudeorchestrator.spec.plist` (weekly Sun 02:00)
- `scripts/launchd/com.claudeorchestrator.chaos.plist` (weekly Sat 02:00)
- `scripts/launchd/com.claudeorchestrator.scout.plist` (weekly Sun 03:00)
- `scripts/launchd/com.claudeorchestrator.deploy.plist` (nightly 02:30)
- `scripts/launchd/com.claudeorchestrator.roi.plist` (daily 00:15)
- `SPEC.md` (template — copy into each managed repo)

### Dashboard additions (web/pages/index.vue)
- NL analytics search box (calls edge function `ask`)
- Project health + active goals section
- Action inbox (v_action_inbox)
- Two-key approval enforcement (2-KEY badge, step-by-step UI)
- Transactions panel (create + list `txns`)
- Confidence chip on every task card
- Runs history table with Replay button
- ROI panel ($/merge, pass rate per project)

## Env vars still needed from you

| Var | Where | Purpose |
|-----|-------|---------|
| `ANTHROPIC_API_KEY` | Supabase edge function secrets | NL analytics (`ask` function) |
| `METRICS_URL` | runner `.env` + deploy plist | Canary evaluation endpoint |
| `CANARY_MAX_ERROR_RATE` | runner `.env` | e.g. `1.0` |
| `CANARY_MAX_P95_MS` | runner `.env` | e.g. `500` |
| `MUTATION_CMD` | runner `.env` (optional) | e.g. `npx stryker run` |
| `PROPERTY_CMD` | runner `.env` (optional) | e.g. `npm run test:prop` |
| `CHAOS_ENABLED=true` | staging runner `.env` only | Enable chaos drills |

## Decisions for you

1. **Deploy edge function**: `supabase functions deploy ask` — needs `ANTHROPIC_API_KEY` set in Supabase dashboard secrets.
2. **Install launchd plists**: Run `scripts/setup-scheduler.sh` once it's updated to include the new plists (or install manually with `launchctl load`).
3. **SPEC.md per repo**: Copy `SPEC.md` template into each managed repo and fill in the invariants section.
4. **Canary**: Only activates when `METRICS_URL` is set. Can stay unset until you have a real metrics endpoint.
5. **Chaos**: Only activates when `CHAOS_ENABLED=true`. Set on a staging runner, not prod.
6. **Transaction coordinator**: Tags tasks with `note: 'txn:<id>'` to join a transaction. Create the transaction in the dashboard first.

## Still open (from v3.2 list)
- Embeddings upgrade for knowledge + context_retrieval (currently keyword fallback)
- Batch API for off-peak passes
- Supabase-branch digital-twin + Vercel preview per PR
- `scripts/setup-scheduler.sh` update to install the 6 new plists
