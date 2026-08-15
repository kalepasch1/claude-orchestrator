# beethoven orchestrator: operator review gate, wave timeline, notifications, attribution, clarifying intake, Illuminati co-think

SUBMITTED-BY: kale@smrter.us (Macey/Piper, operator) via Cowork strategy session 2026-07-27.

Objective: the operator has mandated that all agent branches merge to the dev/staging branch for FINAL OPERATOR REVIEW before any push to prod, with notification when a batch is ready and a graphical view of upcoming waves/merges. Also: full attribution of prompts and steering decisions, clarifying questions at prompt submission, and Madeus consulting Illuminati's CADE during planning. All work is in this repo (runner/ + web/ + supabase/).

## 1. Staging→prod human gate (HIGHEST PRIORITY — currently prod promotion is fully automatic)
- `runner/release_train.py` currently promotes the staging branch (`ORCH_STAGING_BRANCH`, default `orchestrator/dev`) to prod automatically once QA is green and batch/cadence floors are met. Insert an operator approval gate: when a staging batch passes QA and meets floors, DO NOT push to prod; instead create an approval card (kind `release`) via the existing approvals system (`runner/approval_queue.py`) containing: project, staging branch head SHA, list of included agent branches/slugs with one-line descriptions, diffstat summary, QA results, and expected deploy targets. Only promote to prod after the card is `approved`. Support an env escape hatch `ORCH_RELEASE_AUTOPROMOTE=true` to restore old behavior (default false).
- Deny/defer on the card requeues the batch without losing state. Record `decided_by` from the approval.
- Proof: new test in `runner/tests/` showing release_train stops at pending card and promotes only after approval; existing release_train tests still pass.

## 2. Ready-for-review notifications (currently broken)
- `runner/notify.py` and `runner/digest.py` shell out to `scripts/notify.sh` which DOES NOT EXIST — both silently print to stdout. Create `scripts/notify.sh` (Slack webhook + Resend email, env-driven, no secrets committed) and/or route notify.send() through the working `runner/approval_push.py` path (notifications table + RESEND_API_KEY + signed one-click links).
- When a release approval card (from item 1) is created, immediately notify the operator (email kalepasch@gmail.com audience per approval_push.py) with: project, batch size, wave summary, and a deep link to the review page (item 3).
- Proof: unit test that notify.send() invokes the transport (mocked) instead of falling through to print; a dry-run script demonstrating card→notification.

## 3. Wave/merge timeline dashboard in Madeus (web/)
- New page `web/pages/waves.vue` (linked from Mission Control): a graphical timeline showing, per project: (a) the current staging batch — which agent branches are merged in, fill progress toward MIN_BATCH, elapsed time toward the cadence floor, ETA of the next release wave; (b) the merge-train queue order (from approvals + merge_train ordering) — what merges next and in what order; (c) upcoming waves — queued/running tasks grouped by expected wave with a short description each (task title/prompt first line); (d) pending release approval cards with one-click approve/deny (reuse ApprovalCard/DecisionBrief components).
- Data: expose a `web/server/api/waves.get.ts` aggregating tasks, approvals, and staging state. Poll or Supabase realtime (pattern in `web/composables/useFleetWebSocket.ts`).
- The operator must be able to look at this page and decide "do I release now or wait for the next wave." Show expected next waves with times + short descriptions.
- Proof: `npx vue-tsc --noEmit` clean for web/; page renders with seeded fixture data in a component test.

## 4. Attribution: submitters and steering decisions
- Migration: add `submitted_by uuid null references auth.users(id)` and `submitted_by_label text null` to `tasks`. Madeus intake (`web/server/api/tasks/intake.post.ts`) must persist the authenticated user id (it already resolves one via requireConnectorUser and then discards it). Drop-box path: `runner/intake_watcher.py` parses an optional `SUBMITTED-BY:` line from PROMPT-*.md frontmatter into `submitted_by_label`, and slugs/notes carry it through planner decomposition.
- New table `steering_events` (id, task_id nullable, project, actor_id nullable, actor_label, event_type enum: clarification_answer | redirect | approval_rationale | fleet_control | kill_switch | release_decision, rationale text, payload jsonb, created_at). Write rows from: approval decisions (approval_merge / release gate), fleet_control actions (runner/fleet_control.py — include requested_by), clarification answers (item 5), and kill-switch flips.
- Surface: Madeus task detail + waves page show submitter and steering history. Git: agent commits append `Steered-By:`/`Prompt-Source:` trailers (do NOT change the enforced author identity — Vercel blocks other authors).
- Proof: migration applies cleanly; intake writes submitted_by; a steering_events row is written on an approval decision (test).

## 5. Clarifying questions at prompt submission (Madeus + drop-box)
- Add task state `PENDING_CLARIFICATION` to the task_state enum. In `web/server/api/tasks/intake.post.ts`: before queueing, run a cheap-model ambiguity check (scope clear? project certain? material? proof derivable? irreversible actions implied?). If ambiguous, create the task in PENDING_CLARIFICATION with 2-5 generated questions stored in note/payload; Madeus UI (index or inbox) renders the questions inline; operator answers; answers are appended to the prompt as a CLARIFICATIONS block, a steering_events row (clarification_answer) is written, and the task moves to QUEUED. A "skip — proceed as-is" button must exist. Timebox: if unanswered after `ORCH_CLARIFY_TIMEOUT_MIN` (default 120), auto-proceed and note it.
- Drop-box path: `intake_watcher.decompose_freeform()` runs the same check; if ambiguous, file ONE approval card listing the questions instead of decomposing; on approval-with-notes, decompose with the notes appended. Never block silently.
- The "Clarify" stage label in the intake response becomes real. Keep the agent-side rule (agents still don't over-ask); this is submission-time steering only.
- Proof: test that an ambiguous intent yields PENDING_CLARIFICATION with questions and that answering transitions to QUEUED with the CLARIFICATIONS block present.

## 6. Illuminati (CADE) co-think during planning
- Illuminati is a deployed portfolio app (see runner/deployment_bindings.json; live at illuminati-two.vercel.app) exposing CADE evaluation. Integrate it as an advisory input to planning instead of the drifting local duplication: in `runner/planner.py` (and optionally `runner/committees.py`), after generating the task DAG, POST the objective + planned tasks to Illuminati's evaluate endpoint (env `ILLUMINATI_URL` + `ILLUMINATI_API_KEY`; fail-open with a logged warning if unset/unreachable, never block planning). Attach the returned legal/compliance score + flags to each task's note and to the decision record; scores of `escalate|block` create an approval card instead of queueing that task.
- This gives steering-before-building a legal dimension: lawyers/strategy see CADE flags on the waves page before work runs.
- Proof: unit test with a mocked Illuminati response showing flags attached and an escalate → approval card path; planner still works with ILLUMINATI_URL unset.

## Notes for the fleet
- Do not modify prod deploy bindings or push to main/master directly (AGENTS.md rules stand).
- No secrets in code; all new endpoints/keys via env. Operator will provision ILLUMINATI_API_KEY and notification secrets.
- Keep changes wide-shallow and contract-first per planner conventions; runner changes need tests in runner/tests/.
