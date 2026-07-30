# Handoff — model-cost optimization, multi-model QA, and legal-only auto-merge

> Cowork built `model_gateway.py` (multi-provider dispatch) and `judge.py` (cross-model QA +
> legal-risk panel), both compile/import-clean. This handoff wires them so the swarm AUTO-MERGES
> tested work and only stops for genuine legal-counsel items — plus cuts the Opus token burn.

```
Implement three changes. Work in small verified steps; keep the build green.

1. CUT OPUS BURN (data: in 48h Opus ran 39 tasks and ate ~half the notional budget; Haiku ~15x
   cheaper). Retune model selection to prefer cheap models:
   - Default routing: Haiku for mechanical, Sonnet for standard, Opus ONLY when a task is escalated
     (a prior attempt failed) OR flagged high-complexity/security. Raise the Opus bar in
     model_router/bandit so it's the exception, not ~40% of tasks.
   - Add env knobs already respected by claude_cli caps; also add ORCH_DEFAULT_MODEL=claude-haiku
     and ORCH_ESCALATION_MODEL=claude-sonnet, ORCH_HARD_MODEL=claude-opus.
   - Verify per-model mix after a day: Opus should be <10% of tasks.

2. MULTI-MODEL QA + AUTO-MERGE POLICY (the unblock). In runner.py's integrate path, AFTER tests
   pass and the cheap verify passes:
     v = judge.review(task_prompt, git_diff, author_model, project)   # cross-model panel
     if v["verdict"] != "pass":  -> BLOCKED, regression.record, (optional 1 escalated retry)
     elif v["legal_counsel_required"]:  -> file an approval (kind='material') titled
          "Legal review needed: <slug>", why=v["legal_risk"], and DO NOT merge.
     else:  -> AUTO-MERGE (PR-native or ff-merge). No human approval for ordinary work.
   Net effect: tested + judge-passed work merges itself; ONLY genuine legal exposure is gated,
   with the legal risk spelled out on the card. Remove/relax the old blanket confidence gate so it
   no longer parks ordinary passing work (keep the two-key path only for legal + prod-deploy).

3. ENABLE OTHER MODELS (optional, for cheaper QA + second opinions). model_gateway auto-detects a
   provider when its key is present in runner/.env:
     OPENAI_API_KEY=...      (GPT-4o-mini for cheap review; note: ChatGPT Plus/Premium is NOT API —
                              a separate pay-per-token OpenAI API key is required)
     GOOGLE_API_KEY=...      (Gemini 2.0 Flash — very cheap, huge context for whole-repo review)
     DEEPSEEK_API_KEY=...    (deepseek-chat — cheapest bulk QA/rating)
     OLLAMA_HOST=http://localhost:11434  (FREE local model for costless QA/rating)
   judge.py automatically uses a DIFFERENT family than the author (catches blind spots). Route
   mechanical sub-tasks (lint fixes, renames, doc updates) to the cheapest capable provider.

4. BACKFILL: re-queue the existing 141 BLOCKED tasks so they flow through the new policy (they
   already passed tests once). Cap concurrency so it doesn't spike.

5. MODEL TRIAGE (built + tested): route ALL model selection through model_policy.choose(
   task_class, agentic, need). It already prefers free(local)/subscription(Claude $0)/cheap-API
   and reserves Opus for hard/security/legal only — this IS the Opus-retune. Verified: build->Haiku,
   only hard/security/legal->Opus. For NON-agentic sub-tasks (qa/review/rating/mechanical) call
   model_gateway.complete(provider, model, ...) with the policy's pick (uses DeepSeek/Gemini/Ollama
   when their keys are set). Credit-exhaustion tranche: if Claude subscription is rate-limited,
   account_pool rotates Claude accounts; non-agentic work falls to the cheapest API/local.

6. CONTROLLED AUTO-MERGE ROLLOUT (already scoped in DB): projects now have `auto_merge` +
   `confidence_threshold`. Only `tomorrow` is auto_merge=true (threshold 0.4). The integrate policy:
     if project.auto_merge AND tests pass AND judge.verdict=='pass' AND not legal_counsel_required:
         AUTO-MERGE (no human approval)
     elif legal_counsel_required: file approval (kind='material') with the legal risk explained
     else: BLOCKED (only for auto_merge=false projects or judge fail)
   PROVE IT ON `tomorrow` FIRST. Once MERGED count for tomorrow rises cleanly with no bad merges,
   flip the others: `update projects set auto_merge=true, confidence_threshold=0.5;` (I'll do this
   step once tomorrow's proof looks good).

FINISH: report the new model mix (Opus %), confirm tomorrow is auto-merging cleanly (MERGED rising),
and that legal-gated cards explain the specific legal risk. Then we expand to all 10 projects.
```
