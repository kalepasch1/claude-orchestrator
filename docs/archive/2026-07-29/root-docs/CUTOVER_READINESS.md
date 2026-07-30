# Multi-Vendor Routing Cutover Readiness Report

**Date:** 2026-07-14
**Commit:** `ca911ff` (master)
**Status:** READY FOR PRODUCTION

---

## 1. What Changed

Four routing files updated to Jul 2026 models and subscription-first tiers:

| File | Key Changes |
|------|-------------|
| `tier_router.py` | Groq free + Google AI Studio free added to `_SUB_PROVIDERS`; all models updated (Sonnet 5, GPT-5.4, Gemini 3.x, DeepSeek V4) |
| `model_gateway.py` | Full PRICES table updated; groq/xai added to `available()`; Gemini 3-flash default |
| `swarm_executor.py` | PROVIDERS and `_PRICES` updated to Jul 2026 models |
| `vendor_capabilities.py` | Opus pricing fixed ($5/$25); DeepSeek V4 1M ctx; new Grok models |

## 2. Subscription-First Routing Order

The routing priority ensures $0-marginal-cost paths are exhausted before API billing:

| Priority | Provider | Model | Cost | Limit |
|----------|----------|-------|------|-------|
| 0a | Claude Max | Haiku/Sonnet 5/Opus | $0 marginal | 3 plans |
| 0b | Groq free tier | Llama 3.3 70B | $0 | 30 RPM, 1000 RPD |
| 0c | Google AI Studio free | Gemini 3 Flash | $0 | 1500 RPD |
| 0d | ChatGPT Plus/Pro | GPT-5.4-mini (via aider) | flat monthly | subscription tokens |
| 0e | Gemini Advanced | Gemini 3.5 Flash (via aider) | flat monthly | subscription tokens |
| 1+ | API providers | DeepSeek V4, Groq API, Gemini API, xAI, OpenAI, Anthropic | per-token | budget-gated |

**Guards in place:**
- `subscription_guard.py` strips `ANTHROPIC_API_KEY` to prevent accidental API billing
- `key_broker.py` refuses Anthropic API calls — all Claude goes through claude-cli/subscription
- `ORCH_TIER_MODE=sub_first` (default) always tries subscriptions before API
- `budget.paid_allowed()` gates all API spend

## 3. Cost Comparison (per 1M tokens, input/output)

| Provider | Model | Input | Output | Notes |
|----------|-------|-------|--------|-------|
| DeepSeek | v4-flash | $0.14 | $0.28 | Cheapest API, 1M ctx |
| Groq | Llama 3.1 8B | $0.05 | $0.08 | Fastest inference |
| Google | Gemini 3 Flash | $0.50 | $3.00 | Good balance |
| xAI | grok-build-0.1 | $1.00 | $2.00 | Coding-optimized |
| OpenAI | GPT-5.4-nano | $0.20 | $1.25 | Ultra-cheap OpenAI |
| Anthropic | Sonnet 5 | $3.00 | $15.00 | Best code quality |

## 4. DB Migration Status

Migration `0040_vendor_routing_tables` applied to Supabase project `eatfwdzfurujcuwlhdgj`:

| Table | Purpose | Status |
|-------|---------|--------|
| `routing_decisions` | Every routing choice logged | Created, test data verified |
| `shadow_comparisons` | Primary vs shadow result pairs | Created |
| `skill_outcomes` | Cowork skill execution records | Created |
| `creative_spend` | Creative AI budget tracking | Created |
| `vendor_capabilities` | Capability matrix snapshot | Created |

RLS enabled on all tables. Service role has full access; authenticated users have read access for dashboarding.

## 5. Shadow Routing Verification

Test routing decisions inserted and verified:
- Claude Haiku for easy/build tasks (sub tier, $0)
- Claude Sonnet 5 for mid/refactor tasks (sub tier, $0)
- Claude Opus for critical/security tasks (sub tier, $0)
- Groq Llama 3.3 70B for fast triage overflow (sub tier, $0 free)
- DeepSeek V4 Flash for API fallback ($0.00028/task)

To enable shadow mode: `ORCH_COWORK_SHADOW=true`

## 6. Rollback

If issues arise:
1. `git revert ca911ff` — reverts all 4 files to pre-update state
2. The DB tables are additive (no existing tables modified) — safe to leave in place
3. Set `ORCH_TIER_MODE=api_only` to bypass subscription routing entirely

## 7. Remaining Gaps

| Gap | Impact | Mitigation |
|-----|--------|------------|
| ChatGPT Plus doesn't grant API access | aider UI automation required for GPT sub tokens | Falls through to API if aider unavailable |
| Groq free tier rate limits (30 RPM) | Can't handle burst traffic | Overflow to Google AI Studio free or API |
| Fleet git contention | Agent branches reset working tree during checkouts | Changes committed atomically; consider git worktrees |
| No auto-push to origin | Commit is local only | `git push` needed to propagate |
