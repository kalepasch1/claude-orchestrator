# Handoff v3.5 — cross-app capability layer complete

All six handoff items are done, live in the DB, and the seed demo ran clean.

## What was done (this session)

### DB — migration 0006 applied to live (eatfwdzfurujcuwlhdgj)
- `tasks.capability_slug text` — lets runner tag which capability a task instantiated
- `capability_evals.updated_at` — tracks when a real-world pass/fail was written back
- RLS insert policies for `capability_instances` and update policy for `capability_evals`

### Dashboard (`web/pages/index.vue`)
| Section | What it shows |
|---------|--------------|
| **Capabilities** | Table: name/slug, status badge (experimental/trusted/productizable/retired), maturity score, domain, source app + consent tick, active instance list |
| **Capability radar** | Proposals from `approvals` where `kind=proposal`, grouped by capability slug; each shows RICE components (reach/impact/confidence/effort); **Productize** button calls `/api/go-to-market` |

### Edge function — `supabase/functions/go-to-market/index.ts` (deployed)
POST `{slug, target_project, product_name}` — validates consent + productizable status, instantiates capability, queues `gtm-<slug>` build task with `capability_slug` tagged.
Server-side proxy at `web/server/api/go-to-market.post.ts`.

### Federated improvement loop (`runner/runner.py`)
`_update_capability_eval(cap_slug, passed)` fires in `record()` whenever `task.capability_slug` is set:
1. Inserts a `real-world` eval row with `last_pass = (tests_ok AND integrated)`
2. Recomputes `capability_versions.eval_pass_rate` from all evals for that capability
3. `maturity.recompute()` (daily) picks up the updated rate automatically

### Versioned contract enforcement (`runner/capability.py`)
`version(cap_id, semver, spec, contract=None)` now:
1. Diffs old vs new contract on required `inputs` and `outputs`
2. For any breaking change (removed required field, added required field), files an `approvals` card for **every active consuming app** (`capability_instances` where `status=active`) — no silent breakage

### Embedding dedup + semantic radar (`runner/capability.py`, `runner/capability_radar.py`)
- **publish()**: cosine-similarity check against all existing capabilities (threshold `CAP_DEDUP_THRESHOLD`, default 0.95) when `EMBED_PROVIDER` is set — warns on near-duplicate before inserting
- **radar.run()**: embedding-based semantic matching as primary path (app profile vs capability domain); falls back to LLM when `EMBED_PROVIDER` is unset

### Launchd schedules (new plists + wired in `setup-scheduler.sh`)
| Plist | Schedule | Job |
|-------|----------|-----|
| `com.claudeorchestrator.maturity` | Daily 02:30 | `maturity.py` recompute |
| `com.claudeorchestrator.radar` | Mon 03:00 | `capability_radar.py` cross-app proposals |
| `com.claudeorchestrator.demand` | Mon 04:00 | `demand_mining.py` PII-stripped demand signals |

### Seed demo (`runner/seed_demo.py`)
Idempotent end-to-end: entity-formation filing → publish → 11 synthetic evals (pass_rate=0.909) → 2 instances → `maturity.recompute()` → **status=productizable, maturity=94.54** → radar filed 2 proposals → privacy audit ALL CLEAN.
Run: `cd runner && python3 seed_demo.py`

## What was already done (found complete from v3.4)
- `context_retrieval.py` — already uses `context_embed.ce.rank()` for semantic file ranking
- `batch_pass.py` + `periodic.py batch` — Batch API fully wired; `run_batch()` in periodic.py
- `pr_integrate.py` + `supabase_twin.py` — digital-twin create/delete already wired on PR open/close
- `.github/workflows/supabase-preview.yml` — full GitHub Actions workflow for PR-based Supabase branching + Vercel preview env injection

## Privacy path — confirmed scrubs on every entry point
| Path | Scrub calls |
|------|------------|
| `distill.distill()` | input text, model output (double-scrub), each synthetic eval input |
| `capability.publish()` | summary, spec |
| `capability.version()` | spec |
| `seed_demo.py` | audits all three DB fields at end |

## Env vars to set (not yet configured)
| Var | Where | Purpose |
|-----|-------|---------|
| `ANTHROPIC_API_KEY` | Supabase edge function secrets | `ask` NL analytics function |
| `EMBED_PROVIDER` + key | `runner/.env` | Activates embedding dedup + semantic radar |
| `METRICS_URL` | `runner/.env` | Canary deploy evaluation |
| `CHAOS_ENABLED=true` | staging `.env` only | Chaos drills |
| `REQUESTS_FILE` | `runner/.env` | Demand mining source (or use `requests` table) |

## Secrets to add to GitHub repo
Required for `supabase-preview.yml` to work on real PRs:
- `SUPABASE_ACCESS_TOKEN` — from app.supabase.com/account/tokens
- `SUPABASE_PROJECT_REF` — `eatfwdzfurujcuwlhdgj`
- `SUPABASE_DB_PASSWORD`
- `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`

## Decisions for you
1. **Install new launchd plists**: re-run `scripts/setup-scheduler.sh` — it now includes maturity, radar, demand plists
2. **Deploy `ask` edge function**: `supabase functions deploy ask` after setting `ANTHROPIC_API_KEY` in Supabase dashboard secrets
3. **Add GitHub repo secrets** for the Supabase digital-twin workflow
4. **Set `EMBED_PROVIDER`**: add `EMBED_PROVIDER=openai` + `OPENAI_API_KEY` to `runner/.env` to activate semantic dedup and radar; leave blank to keep LLM fallback
5. **`requests` table or `REQUESTS_FILE`**: feed demand_mining — either insert rows into a `requests` table (project, text) or point `REQUESTS_FILE` at a newline file of user request strings

## Still open (nice to have)
- `runner/.env.example` — update with new vars (`REQUESTS_FILE`, `CLAUDE_BIN`, `CAP_DEDUP_THRESHOLD`)
- `go_to_market.launch()` Python path requires the target app to have a row in `projects`; the edge function path works for any app name
