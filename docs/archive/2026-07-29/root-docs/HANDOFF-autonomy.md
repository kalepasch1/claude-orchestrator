# Handoff — autonomy layer (feedback loop + per-app loops + session-watch + resource governance)

> Cowork built and WIRED the core; live schema is at 0007. This consolidates and REPLACES
> the earlier feedback-loop handoff. Built modules (import-clean): feedback.py +
> feedback_review.py (agent→orchestrator learning), loops.py (per-app learn/remediate/
> optimize/review loops) + meta_loop.py (loop on a loop, cross-deploy best loop configs),
> session_watcher.py (reads paused/finished Claude Code transcripts → next step + harvests
> feedback from INTERACTIVE sessions), resource_governor.py (prunes merged worktrees/caches/
> logs + live-throttles MAX_PARALLEL on disk/RAM pressure). runner.py honors the live throttle
> and schedules all of these in-process. Finish the items below.

```
Continue the Claude Orchestrator autonomy layer. Modules above exist + are scheduled (see
runner.py _SCHEDULE). Live DB at migration 0007. Work in small verified steps; report a checklist.

A. CLOSE FINISHED VS CODE TABS / sessions (the one piece Cowork can't do headlessly):
   - session_watcher already detects finished sessions and the resource_governor reclaims their
     worktrees. Add the actual tab close: a VS Code task/command or a tiny extension that, given a
     finished session id, runs `code` CLI / `workbench.action.closeActiveEditor` for that tab; OR a
     computer-use helper. Gate on session_actions.status='finished'. NEVER close a session whose
     transcript shows unfinished phases/waves — confirm 'done' first.
   - Verify worktree reclamation: after close, run resource_governor.prune() and confirm disk freed.

B. RESOURCE GOVERNOR depth: add RAM via psutil (optional dep), add a PREDICTIVE check (fit a line
   to recent resource_events disk values; if it will breach DISK_HARD within ~2h, prune/throttle
   now). Add node_modules + Docker + ~/Library/Caches to the prune candidates behind a flag.
   Surface a dashboard gauge (disk %, free GB, current throttle).

C. SESSION NEXT-STEP quality: improve session_watcher._decide to also read the LAST USER MASTER
   PROMPT and the task's phases/waves, so "best next step" continues a multi-phase master prompt
   correctly (don't mark done while phases remain). When SESSION_AUTO_CONTINUE=true, queue the
   follow-up; otherwise file it as a decision card in the dashboard.

D. LOOP-ON-A-LOOP depth (meta_loop): besides cross-deploying cadences, have it TUNE each loop
   (raise remediate frequency for flaky apps, lower optimize frequency for stable ones), and ALWAYS
   ask the Claude Code agents (via the feedback instruction already in prompts) "how could this
   app's loop or the app itself be improved?" — then route those answers through feedback_review.

E. FEEDBACK AUTO-EXPERIMENTS (the 10x): when feedback_review clusters a concrete knob change,
   A/B it via eval_harness.py (current vs proposed) on held-out tasks BEFORE adoption; only file
   'recommended: adopt' if the candidate wins. Per-category owners apply an APPROVED change on a
   branch through CI (revertible): context→CONTEXT_MAX_FILES, model→bandit, rate_limit→concurrency,
   strategy→planner, guardrail→guard rules, prompt→caching prefix.

F. DASHBOARD (web/pages): add "Loops" (per-app type/health/last-run, enable toggle), "Sessions"
   (paused/finished + next_action + a 'Run it' button), "Resources" (disk/throttle gauge + recent
   prunes), and "Feedback" (counts by category/severity/status + a box to add human feedback).
   Keep `npm run build` green.

G. SAFETY: resource_governor must NEVER delete a worktree with uncommitted changes or an unmerged
   branch; only `--merged main` agent/* worktrees and rebuildable caches. session-close must never
   close an in-progress session. Add tests for both guards.

H. CREDENTIALS & SPEND GOVERNANCE (built + WIRED; schema 0008). Modules: secrets_manager.py
   (stores only REFERENCES; values stay in env/keychain/doppler/1Password; injects per-project
   into the task env, never logged), kill_switch.py (runner checks is_paused() globally + per
   project before claiming/running), credential_broker.py (resolve→provision via provider mgmt
   API→ELSE file a credential_request + approval; PAYMENT/manual is the ONLY thing that prompts
   you), rotate_keys.py (rotate via provider mgmt API; mark old revoked), usage_meter.py
   (per-provider/project external spend + budget pause), providers.py (per-provider plugins).
   Finish:
   - DASHBOARD: a "Spend & keys" view — per-project/provider usage from v_provider_spend_mtd +
     budgets with bars; a big red STOP button (writes controls.paused=true via the controls RLS
     policy — instant halt) and Resume; a "Rotate" button per secret that enqueues a control task
     the runner runs via rotate_keys; a "Credential requests" list (payment_required highlighted).
   - PROVIDER PLUGINS: fill providers.py stubs with real management-API calls for the providers you
     use (OpenAI admin keys, Supabase service-key rotation, Vercel env update, etc.). Keep the
     "payment_required/manual → prompt the human" path; NEVER auto-enter payment.
   - SECRETS HYGIENE (enforce + test): the value of a secret must NEVER be written to Supabase,
     logs, the web app, or git — only refs. Add a test asserting `secrets` rows contain no value-
     looking strings, and that inject_env output is never logged.
   - On HARD kill (optional): offer "stop + revoke keys" for a security panic button (rotate_keys
     with immediate revoke), separate from the normal pause.
   - DEPLOY ENV SYNC: after rotate, update the live deploy env (Vercel/Supabase) with the new ref.

I. SPEND OPTIMIZATION (10x): the orchestrator should continuously trim external spend without
   hurting value — usage_meter.optimize() flags near-cap/idle providers; extend it to suggest
   cheaper tiers/routes, detect unused subscriptions (spend but no successful outcomes), and feed
   those as proposals. Add per-project provider budgets with auto-pause (mirrors budget.py).

FINISH: checklist, loops/sessions/resources/feedback + spend/keys live in the dashboard, the
governor verified to free disk + throttle under pressure, the kill switch verified to halt the
runner instantly, secrets confirmed never persisted as values, and the feedback auto-experiment
gate running before any self-change is adopted.
```
