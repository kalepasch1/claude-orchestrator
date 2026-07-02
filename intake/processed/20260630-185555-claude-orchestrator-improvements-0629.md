PROJECT: claude-orchestrator

# NOTE: these target the orchestrator repo itself (runner/ + web/ + supabase/), NOT a product
# repo. If your runner keys on the product list, route this to the orchestrator-self build or
# rename PROJECT to your registered self-project (you have projects named 'beethoven' /
# 'ORCHESTRATOR' in approvals). One deliverable per task; each has a concrete proof.

- id: structured-approval-fields
  title: Require why/value/risk/alternatives + content-hash on every generated approval
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_approval_fields.py` exits 0
  prompt: |
    Centralize approval creation. Add runner/approvals.py `propose_approval(db, **fields)` that every
    generator (anomaly.py, auto_experiment.py, capability_radar.py, demand_mining.py, feedback_review.py,
    fix_propagation.py, meta_loop.py, opportunity_scout.py) calls instead of raw db.insert("approvals").
    It REQUIRES why, value, risk, alternatives (>=1) and computes a normalized content hash
    (lowercase, collapse whitespace, strip dates/ids) stored in detail as `hash=<hex>`. Refuse to insert
    if any required field is missing. Migrate the existing call sites. Add runner/tests/test_approval_fields.py
    asserting missing-field rejection + stable hashing.

- id: approval-dedup-at-source
  title: Skip generating an approval whose normalized hash already exists open
  material: no
  model: sonnet
  depends: [structured-approval-fields]
  proof: `python3 -m pytest runner/tests/test_approval_dedup.py` exits 0
  prompt: |
    In propose_approval (runner/approvals.py), before insert, query approvals for an existing row with
    the same (project, hash) in status pending|approved; if found, return that id and DO NOT insert a
    duplicate (this is why the 142 backlog accumulates near-dupes; the legal-bot prompt had 5 identical
    blocks). Add runner/tests/test_approval_dedup.py proving a second identical candidate yields no new row.

- id: pre-generation-gate
  title: RICE x confidence x self-review gate before any approval is created
  material: no
  model: sonnet
  depends: [approval-dedup-at-source]
  proof: `python3 -m pytest runner/tests/test_proposal_gate.py` exits 0
  prompt: |
    Add a gate inside propose_approval: only create an approval if parsed/assigned RICE >= RICE_MIN
    (env, default e.g. 5) AND confidence >= CONF_MIN AND it passes a cheap one-shot self-review
    (model_router picks haiku) that answers "is this concrete, non-duplicative, and worth a human's
    attention? yes/no + reason". Below bar => log to outcomes as skipped(reason), do not insert.
    Goal: generate ~10x fewer, higher-signal items. Add runner/tests/test_proposal_gate.py with a
    low-RICE item skipped and a high-RICE item passed (mock the self-review call).

- id: policy-as-code-approvals
  title: Operator-authored approval policies (auto-approve / auto-deny / require-2) with a hard safety floor
  material: yes
  model: opus
  depends: [structured-approval-fields]
  proof: `python3 -m pytest runner/tests/test_policy_engine.py` exits 0
  prompt: |
    Add a `policies` table (supabase/migrations) + runner/policy_engine.py. A policy = {scope/project,
    predicate(kind, rice_min, risk_max, path_globs, material), action: auto_approve|auto_deny|require_2}.
    Evaluate on each new + pending approval. HARD FLOOR that no policy can override: never auto_approve
    when project in {apparently,tomorrow} AND material, or when paths touch compliance/auth/RLS/schema/
    migrations/money/legal. Auto-decisions write decided_by='policy:<id>' + an outcomes row. This SUBSUMES
    a separate tiered-auto-approve. Add runner/tests/test_policy_engine.py covering: legal+material never
    auto-approved; low-risk infra auto-approved; require_2 sets a second-approver gate.

- id: intake-dedup-conflict
  title: Dedup + file-conflict detection across intake files before queueing
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_intake_dedup.py` exits 0
  prompt: |
    Multiple sessions drop intake files (smarter/tomorrow/apparently landed together). In the ingest
    path, before creating tasks: skip tasks whose (project,id) or prompt-hash already exist as a task;
    parse referenced file paths from each prompt (lines like 'File:' or `server/...`) and when two queued
    tasks touch the same path, auto-add a depends chain so worktrees don't conflict. Add
    runner/tests/test_intake_dedup.py for dedup + auto-chaining.

- id: quality-eval-gate
  title: Gate merges on golden-set eval score, not just the compile/test proof
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_eval_gate.py` exits 0
  prompt: |
    Extend the runner verify step: a task may declare an `eval` (golden set + min score) alongside `proof`.
    Merge is blocked unless eval score >= threshold. Reuse capability_evals/model-eval patterns; first
    consumers: Apparently doc-intake recall/precision golden set and a pricing-model golden set. Persist
    eval results. Add runner/tests/test_eval_gate.py: a change that passes tsc but drops eval score is blocked.

- id: champion-challenger-shadow
  title: Shadow-replay legal/pricing prompt changes on held-out cases before they deploy
  material: yes
  model: opus
  depends: [quality-eval-gate]
  proof: `python3 -m pytest runner/tests/test_shadow_eval.py` exits 0
  prompt: |
    Before any prompt_refinement to a legal bot (Apparently) or a pricing-model change (Tomorrow) is
    allowed to deploy, replay the challenger vs the live champion over a held-out set of past
    opinions/quotes and diff outcomes. If verdicts flip on settled matters beyond tolerance, block and
    route to human. Add runner/tests/test_shadow_eval.py with a regression-inducing challenger blocked
    and a benign one allowed.

- id: verification-gated-autoapply
  title: Post-merge self-verify + auto-rollback on regression
  material: yes
  model: opus
  depends: [policy-as-code-approvals]
  proof: `python3 -m pytest runner/tests/test_verify_rollback.py` exits 0
  prompt: |
    After an approved/auto-approved change merges, re-run its proof (and eval if present) and check
    tracked metrics; on failure or regression, auto-revert the merge commit and re-open the approval with
    the failure attached. Wire the unused approvals.post_apply_verification / auto_rollback_trigger
    intent. Add runner/tests/test_verify_rollback.py: a failing post-merge verify triggers a revert.

- id: incident-to-ci-guard
  title: Turn every failure-class / postmortem into a permanent CI guard + regression test
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_incident_guard.py` exits 0
  prompt: |
    When a task fails in a recognizable class (migration name mismatch/P3018, RLS, type-baseline
    increase) or a postmortem is recorded, auto-generate a lint rule/CI guard + a regression test and
    FILE it to the affected repo's intake (generalizing Apparently's lint:migrations win). Add
    runner/tests/test_incident_guard.py for class-detection + guard emission.

- id: examiner-provenance
  title: Signed provenance record on every autonomous merge (audit/exam defensible)
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_provenance.py` exits 0
  prompt: |
    Each autonomous (or approved) merge writes a signed provenance row {commit, task_id, why, proof_result,
    approver|policy, model, cost, ts} using an Ed25519 signature (mirror Tomorrow's verifiable-proof C1
    pattern). Provide a verify function that recomputes the digest. Add a `provenance` table + 
    runner/tests/test_provenance.py (sign/verify + tamper rejection).

- id: cross-repo-compute-allocation
  title: Portfolio allocator — spend the global budget on highest throughput-per-dollar across ALL repos
  material: no
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_portfolio_allocator.py` exits 0
  prompt: |
    Replace per-repo greedy task selection with a portfolio allocator: rank ALL ready tasks across repos
    by expected value/$ (RICE x success-prob from bandit.py / outcomes, divided by predicted cost from
    the cost model) and dispatch within the global cost cap, not per-repo. Add
    runner/tests/test_portfolio_allocator.py asserting it prefers higher value/$ and respects the cap.

- id: capability-fix-propagation
  title: Auto-propagate a fix/capability landed in one repo to others that share the pattern
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_fix_propagation.py` exits 0
  prompt: |
    Extend runner/fix_propagation.py: when a fix or capability lands, semantic-match (knowledge pgvector)
    against the other repos; if the same bug/pattern is present, auto-file the same fix to their intake
    (as a proposal, human-gated if material). Add runner/tests/test_fix_propagation.py for match->emit.

- id: shared-materiality-policy
  title: One versioned materiality definition consumed by all three classifiers (kill the drift)
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_materiality.py` exits 0
  prompt: |
    Materiality is defined separately in Apparently (gitAutomation), Tomorrow (self-improvement-runner),
    and the orchestrator — and it has drifted (a rule added to one classifier but not its mirror).
    Create one versioned materiality policy (union of the three rule sets) as a shared module/table; have
    each classifier import it. Add runner/tests/test_materiality.py with a drift test that FAILS if any
    local classifier diverges from the shared policy.

- id: realized-roi-attribution
  title: Attribute realized ROI to merged changes; auto-pause negative-ROI loops
  material: no
  model: sonnet
  depends: [examiner-provenance]
  proof: `python3 -m pytest runner/tests/test_roi_attribution.py` exits 0
  prompt: |
    Proposals claim value ("$4-8k/mo AI-call savings"). After merge, track the metric it claimed
    (outcomes/provider_usage/cost), compute realized delta over a window, and down-weight or pause
    loops/categories whose realized ROI is negative. Add runner/tests/test_roi_attribution.py.

- id: learn-from-decisions
  title: Feed human approve/deny back so rejected proposal-types stop being generated
  material: no
  model: sonnet
  depends: [structured-approval-fields]
  proof: `python3 -m pytest runner/tests/test_decision_feedback.py` exits 0
  prompt: |
    On each decided approval, record an outcome keyed by (project, source/category, decision); have the
    generators + pre-generation-gate down-weight categories with low historical approval rates (calibrate
    the existing "approval likelihood" prediction against reality). Add runner/tests/test_decision_feedback.py.

- id: approval-load-forecast
  title: Forecast the week's human-approval load + schedule one batched review
  material: no
  model: haiku
  depends: []
  proof: `python3 -m pytest runner/tests/test_load_forecast.py` exits 0
  prompt: |
    From the known cron cadence + recent generation rate, forecast upcoming pending-approval volume and
    expose "this week ~N items need you", and schedule a single batched review block instead of a trickle.
    Add runner/tests/test_load_forecast.py for the estimate math.

- id: daily-oversight-digest
  title: Daily "top 3 that actually need you" digest instead of a 142-row inbox
  material: no
  model: haiku
  depends: [structured-approval-fields]
  proof: `python3 -m pytest runner/tests/test_digest.py` exits 0
  prompt: |
    Extend runner/digest.py to send a daily Slack/email digest of the top pending approvals ranked by
    RICE x risk (cap ~3-5), each with one-line why + an approve link, instead of listing everything. Add
    runner/tests/test_digest.py for ranking/cap.

- id: console-all-oversight-tabs
  title: One console with every human-action type (approvals, credentials, controls, verify, secrets)
  material: no
  model: sonnet
  depends: []
  proof: `cd web && npx nuxi typecheck` exits 0
  prompt: |
    web/pages/index.vue already loads approvals/credential_requests/controls/session_actions. Add tabbed
    sections so all human-action types live on one screen: Approvals (existing), Credentials, Controls
    (pause/kill per project), Verify (kind='verify'), Secrets (kind='secret'). Reuse existing
    decide()/supabase patterns. No schema changes. Verify with nuxi typecheck.

- id: console-killswitch
  title: Per-project pause/kill-switch from the console (runner honors it)
  material: yes
  model: sonnet
  depends: [console-all-oversight-tabs]
  proof: `cd web && npx nuxi typecheck` exits 0
  prompt: |
    Add a pause/resume control writing controls(scope,project,paused,reason,updated_by) and confirm
    runner.py checks controls.paused before claiming tasks for that project (add the guard if missing).
    Material: halts autonomous execution.

OPERATOR:
  - Confirm/adjust PROJECT routing — this targets the claude-orchestrator repo itself, not a product project.
  - Approve the prod-merge of the material tasks (policy engine, quality/eval gate, champion/challenger, verification+rollback, shared-materiality, provenance, killswitch) after CI + eval pass.
  - Slack/email digest + approve-links + provenance signing need the runner's existing Slack/SMTP/Resend creds + an Ed25519 signing key in the runner env.
  - Decide the policy floor + RICE/confidence thresholds (RICE_MIN, CONF_MIN) and the held-out eval/golden sets for Apparently (opinions) and Tomorrow (pricing) before enabling auto-approve or shadow gating.
