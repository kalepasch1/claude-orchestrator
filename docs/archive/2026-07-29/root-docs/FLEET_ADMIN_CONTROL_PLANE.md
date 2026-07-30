# Fleet Admin Control Plane — Implementation

One control plane to run admin ops across all apps, agent-driven, with Bear approving
the ~5% of decisions that need a human — from his Smarter account. Built by promoting
what already existed (the Orchestrator, the Darwin Kernel, Smarter's trust dial,
Apparently's admin-board) rather than building a new app.

## What was built

### 1. Kernel — the shared substrate (`@darwin/kernel/fleetAdmin`)
`packages/darwin-kernel/src/fleetAdmin/`
- **`types.ts`** — canonical `AdminEvent` / `AdminAction`, the four `AdminDomain`s
  (users_access, billing, trust_safety, infra), the severity ladder, and category→domain
  mapping (promoted from Apparently's `admin-board`).
- **`autonomy.ts`** — the four-domain autonomy matrix. `evaluateAutonomy()` computes a
  tier (`auto` | `co_pilot` | `human`) per action from confidence × reversibility ×
  blast radius × money, clamped by a per-domain ceiling. Fail-closed. This is the 5/95
  dial. Infra's ceiling is `co_pilot` — it never silently acts on prod.
- **`constitution.ts`** — the fleet admin constitution overlay (always-escalate verbs +
  safe allows) on the existing `Constitution` shape, so the same signed-receipt machinery
  applies.
- **`govern.ts`** — `governFleetAction()` composes constitution + autonomy + a signed,
  hash-chained receipt in one call. Strictly restrictive: the dial can only lower
  autonomy, never turn an escalate/deny into an allow.
- **`adapter.ts`** — the `FleetAdminAdapter` contract every app implements (emit events,
  propose actions, execute, reverse) + an in-memory adapter for tests.
- **`bridge.ts`** — `FleetApprovalCard` (Why/Value/Risk/Alternatives + receipt digest +
  callback) and `ApprovalDecision` — the vocabulary pushed to Smarter and posted back.
- **`ledger.ts`** — the escalation-learning flywheel: streaks per (domain, action-type),
  promotion candidates after a clean streak, and the fleet-wide "% autonomous" north-star.
- **`plane.ts`** — the control-plane loop (pure, port-injected): `ingestEvent`,
  `governAndRoute`, `handleDecision`. Auto-runs the safe 95% by delegating to the app;
  mirrors the rest to Smarter; executes on Bear's decision; learns from every outcome.

**Tests:** `test/fleetAdmin.test.ts` (15) + `test/fleetPlane.test.ts` (7). Full kernel
suite **81/81 pass; `tsc --noEmit` clean.**

### 2. Orchestrator — the runtime admin control plane
- **`supabase/migrations/0011_fleet_admin.sql`** — `fleet_admin_events`,
  `fleet_admin_actions`, `fleet_approvals`, `fleet_receipts` (append-only),
  `fleet_autonomy_ledger`, `fleet_approvers`. Default-deny RLS; only allow-listed
  approvers can resolve; receipts immutable. **Applied live** to project
  `eatfwdzfurujcuwlhdgj` (claude-orchestrator).
- **`web/server/utils/fleetSupabase.ts`** — Supabase + fetch ports for the plane.
- **`web/server/api/fleet/`** — `ingest.post.ts` (apps push events), `callback.post.ts`
  (Smarter posts decisions), `approvals.get.ts` (the queue), `autonomy.get.ts` (the
  north-star + promotion candidates).

### 3. Smarter — the approval surface (where Bear decides)
- **`server/utils/fleetInbox.ts`** — the mirrored cross-app queue (mock-degradable, uses
  the existing `smarter_collections` store; collection `fleet_cards`).
- **`server/api/fleet/`** — `inbox.post.ts` (receives cards), `index.get.ts` (lists them),
  `decide.post.ts` (Bear approves/rejects → posts back to the Orchestrator callback with
  his session identity + records a trust receipt).
- **`pages/fleet.vue`** — the unified "Fleet Admin" screen: one ranked queue across every
  app, domain-badged, one-tap approve/reject.

### 4. Reference adapter — Apparently
- **`server/utils/fleet-adapter.ts`** — maps `admin-board` posts → `AdminEvent`, pushes to
  the plane, and executes cleared actions (mock-degradable with real side-effect seams).
- **`server/api/fleet/execute.post.ts`** — the delegated execute endpoint.

## The approval feed — round trip

```
app admin-board ──emit──▶ Orchestrator /api/fleet/ingest
      │                         │ governFleetAction (constitution + autonomy + receipt)
      │              ┌──────────┴───────────┐
      │        decision=allow          decision=escalate
      │        delegateExecute()        buildApprovalCard()
      │        (app /api/fleet/execute)      │ pushToSmarter()
      │                                       ▼
      │                         Smarter /api/fleet/inbox  ──▶  pages/fleet.vue
      │                                                            │ Bear taps Approve
      │                         Orchestrator /api/fleet/callback ◀─┘ (his Smarter identity)
      │                         handleDecision(): allowlist ✓ → delegateExecute() → ledger++
      ▼
   signed receipt on every step (fleet_receipts, append-only)
```

**Live state right now** (seeded to prove the wire): the Orchestrator project holds a real
pending approval `act_demo_1` (galop billing chargeback, $180, always-human), and the same
card is mirrored into Smarter's `fleet_cards` collection — so opening Smarter `/fleet`
renders it and Approve/Reject posts back to the Orchestrator callback.

## Approver identity — kalepasch@gmail.com

- Seeded into `fleet_approvers` (role `admin`) on the live Orchestrator project, alongside
  `kale@heretomorrow.us`. The callback enforces this allowlist before executing.
- Smarter's `decide` endpoint takes the approver from Bear's Smarter **session**; env
  fallback `FLEET_APPROVER_EMAIL=kalepasch@gmail.com` for the seed/demo path.
- **One manual step only you can do:** sign in once as `kalepasch@gmail.com` on both the
  Orchestrator dashboard and Smarter (magic-link / Google), so the Supabase **auth** user
  exists. Everything else (allowlist, routing, fallback) is already wired. I can't create a
  verified login on your behalf without your sign-in.

## Env to finish wiring (templates written)
`web/.env.fleet.example` (Orchestrator) and `smarter/.env.fleet.example` (Smarter). Set the
**same** `FLEET_SHARED_SECRET` everywhere, point `SMARTER_INBOX_URL` at Smarter, and set
`FLEET_URL_<PRODUCT>` for each app's execute endpoint.

## Rollout sequence (safe path)
1. Deploy the kernel + Orchestrator endpoints + Smarter inbox (done in code; DB live).
2. Onboard **one** app end-to-end in **shadow mode** — Apparently (adapter built). Emit
   events; let the plane propose but keep everything at `co_pilot` (draft-for-approval).
3. Watch the agreement rate on `/api/fleet/autonomy`. When an action-type earns a clean
   streak, the flywheel offers a promotion — you confirm it (still a human gate).
4. Promote the safest classes to `auto`; fan out to the other apps via the adapter
   (`FLEET_ADMIN_APP_MAP.md`), infra + money gated hardest.

## Amplifier layer (the next 20–500×) — built

Six additive modules in `@darwin/kernel/fleetAdmin`, each pure + tested, wired where it
counts:

1. **Case-based autonomy** (`precedent.ts`) — sets an action's tier from how the most-
   similar PAST cases resolved (feature similarity over the decision log). Wired into
   `governFleetAction` as a **clamp-only** input: precedent can hold or lower autonomy,
   never raise it. Live via the `recentCases` port.
2. **Predictive admin** (`forecast.ts`) — EWMA inter-arrival model forecasts recurring
   events before they fire → pre-staged co-pilot cards. `GET /api/fleet/forecast`.
3. **CADE pre-pass** (`deliberation.ts`) — an advocate/adversary/reviewer conclave (tied
   to CADE's real vector math) attaches the strongest case + strongest objection + a
   dissent score to every human-tier card. Wired into `buildApprovalCard`.
4. **Cross-app incident correlation** (`correlate.ts`) — union-find over shared root-cause
   signals within a window folds events from different apps into ONE incident.
   `GET /api/fleet/incidents`.
5. **Reverse auction on autonomy** (`promotionValue.ts`) — quantifies each earned
   promotion (approvals saved, minutes reclaimed, $ latency-risk avoided) so expanding
   autonomy is a one-tap business decision. `GET /api/fleet/promotions`.
6. **North-star KPI** (`kpi.ts`) — answered-from-plane rate + by-domain breakdown +
   period-over-period trend. `GET /api/fleet/kpi`, plus a **weekly digest** scheduled task
   (`fleet-admin-weekly-digest`, Mondays) that reports it to Bear.

## Amplifier layer II (the next 50–200×) — built

Evidence-backed + self-hardening autonomy. Six more pure, tested modules in
`@darwin/kernel/fleetAdmin`:

7. **Counterfactual replay** (`replay.ts`) — backtests a candidate promotion against the
   whole decision log → measured false-positive rate. Promotion becomes evidence-backed.
8. **Portfolio blast simulator** (`blastSimulator.ts`) — models the correlated exposure
   that would flow through one auto path (daily $, concentration, worst day) before you
   widen autonomy. The thing no per-app tool can compute.
9. **Promotion dossier** (`dossier.ts`) — composes value + replay-safety + blast into one
   verdict; recommends only when valuable AND proven-safe AND low-blast.
   `GET /api/fleet/promotion-dossier`.
10. **Fix propagation** (`propagation.ts`) — one incident's fix is proposed to every other
    app sharing the root-cause signal. One approval → N apps fixed. `POST /api/fleet/propagate`.
11. **Self-rewriting constitution** (`constitutionLearner.ts`) — mines the rejection log
    into materiality-gated amendment proposals (deny / always-escalate / amount-cap). The
    law tightens itself from your decisions. `GET /api/fleet/amendments`.
12. **Adversarial red-team** (`redTeam.ts`) — probes every domain ceiling with synthetic
    edge cases and flags any that would auto-run with harm potential. Autonomy expands AND
    gets safer. `GET /api/fleet/redteam`.
13. **Approver-preference model** (`approverModel.ts`) — learns Bear (per-type approval
    rates, scrutinized domains, active hours, common edits); the queue now orders itself to
    his attention, predicts his call, and pre-fills his usual edit.
    `GET /api/fleet/approver-profile`; wired into `GET /api/fleet/approvals`.

## Amplifier layer III (50–200×+) — the plane governs, optimizes, proves + heals ITSELF

14. **Digital-twin dry-run** (`twin.ts`) — replays any config/constitution change against
    the real action stream with zero side effects; flags regressions (would auto-run a
    previously-rejected action). Every policy change becomes a measured experiment.
15. **Federated cross-app precedent** (`federatedPrecedent.ts`) — privacy-walled priors
    (k-anonymity + DP) so a new app launches already-smart by borrowing mature apps'
    clean-rates. Raw decisions never move. `GET /api/fleet/federated-precedent`.
16. **Economic autopilot** (`economicAutopilot.ts`) — solves the dial against a realized-cost
    loss function (auto vs. human) instead of hand-set thresholds.
    `GET /api/fleet/economic-autopilot`.
17. **Regulator-grade proof pack** (`proofPack.ts`) — per-decision, offline-verifiable proof
    (constitution + autonomy + deliberation + signed receipt). `GET /api/fleet/proof/:id`.
18. **Natural-language control plane** (`nlControl.ts`) — English → compiled rule → twin
    dry-run → confirm. Govern all 9 apps in plain English. `POST /api/fleet/nl-compile`.
19. **Self-healing adapters** (`adapterHealth.ts`) — detects failing/ drifting adapters from
    the execution stream, raises an infra incident, and drafts a code-fix task for the
    orchestrator runner. `GET /api/fleet/adapter-health`.

## Amplifier layer IV (20–500×+) — the plane optimizes, reasons causally + governs itself

20. **Multi-objective Pareto tuning** (`paretoTuning.ts`) — the trade-off frontier across
    cost / risk / approver-load / latency; pick a point on the curve, not one weighting.
    `GET /api/fleet/pareto-tuning`.
21. **Causal incident model** (`causal.ts`) — learns a causal graph from the log (A causes
    B, not just co-occurs) → true upstream root cause + causal propagation. `GET /api/fleet/causal`.
22. **Constitution as a market** (`ruleMarket.ts`) — tight/balanced/lean factions bid; the
    twin scores each against real history; the best-fitting law wins. `GET /api/fleet/rule-market`.
23. **Adversarial co-evolution** (`coevolution.ts`) — a learning adversary vs. the dial finds
    and closes the largest auto-run gap → the provably-safe autonomy envelope.
    `GET /api/fleet/coevolution`.
24. **Portfolio treasury** (`treasury.ts`) — admin ops as a live P&L (approver time saved +
    incident loss avoided − escalation cost). `GET /api/fleet/treasury`.
25. **Dependency-aware queue** (`dependencyQueue.ts`) — bundles related decisions on the same
    subject (termination supersedes refund) so you decide once. `GET /api/fleet/dependency-queue`.

## Amplifier layer V (20–500×+) — closed-loop, pre-cognitive, self-attesting

26. **Closed-loop self-promotion** (`selfPromotionCycle.ts`) — nightly, assembles every earned
    promotion into a dossier, keeps the replay-safe + low-blast set, and hands you ONE
    accept-all card. `GET /api/fleet/self-promotion` + a nightly scheduled task. This is what
    moves the autonomy rate on its own.
27. **Pre-launch world model** (`worldModel.ts`) — projects a new app's day-one autonomy rate,
    blast, and treasury from its expected mix + federated priors, before any adapter code.
    `POST /api/fleet/world-model`.
28. **Cross-app subject reputation** (`subjectReputation.ts`) — fuses fraud/abuse signals across
    apps so a bad actor caught once is caught fleet-wide; clamps autonomy per subject.
    `GET /api/fleet/subject-reputation`.
29. **NL incident commander** (`incidentCommander.ts`) — ask in English; get a causal-root-cause
    + one-tap fix. `POST /api/fleet/incident-commander`.
30. **Proof-of-autonomy attestation** (`fleetAttestation.ts`) — a signed, offline-verifiable
    trust artifact (rate + regression record + red-team envelope). `GET /api/fleet/attestation`.
31. **Time-travel debugging** (`timeTravel.ts`) — replay any past window under any law + attribute
    a drift to the culpable change. `POST /api/fleet/time-travel`.

## Amplifier layer VI (20–500×+) — the plane becomes a product

32. **Published as a Darwin capability** (`capability.ts`) — the plane itself is now a
    registry capability; any orchestrator instantiates governed admin in one line.
    `GET /api/fleet/capabilities`.
33. **Intent-level autonomy** (`intent.ts`) — promote INTENTS, not action-types: "retain this
    churn-risk user" plans refund + apology + priority-support and governs the whole plan as ONE
    decision bounded by the constitution. `POST /api/fleet/intent`.
34. **Continuous constitution A/B** (`shadowAB.ts`) — a challenger law shadow-scores against the
    champion on live traffic; promote when it wins by a margin. `GET /api/fleet/shadow-ab`.
35. **Regret ledger** (`regret.ts`) — post-hoc signals (reversed charge, rollback, reopened
    ticket) become implicit rejections on past auto-runs, feeding precedent + replay + red-team.
    `GET /api/fleet/regret`.
36. **Compliance SKU** (`complianceSku.ts`) — packages the signed attestation + sample proof
    packs into a sellable "Provably-Governed AI Operations" report (Markdown). `GET /api/fleet/compliance-report`.

## Amplifier layer VII (20–500×+) — governed autonomy as a network good

37. **Governance marketplace** (`marketplace.ts`) — a two-sided market for signed constitutions,
    DP-anonymized precedent packs, and intent playbooks; a new org inherits mature policy day one.
    `GET /api/fleet/marketplace`.
38. **Learned intent planner** (`intentPlanner.ts`) — composes an open-ended goal into a bounded
    step plan from past successful exemplars (or a template), still governed as one decision.
    `POST /api/fleet/intent-plan`.
39. **Portfolio objective solver** (`portfolioObjective.ts`) — steers the whole plane toward one
    business goal by choosing the Pareto-frontier dial that maximizes it under constraints.
    `POST /api/fleet/portfolio-objective`.
40. **Counterfactual human model** (`counterfactual.ts`) — runs "what would Bear have done?" on
    every auto action in shadow → real-time divergence/regret. `GET /api/fleet/counterfactual`.
41. **Adversarial bounty market** (`bounty.ts`) — validated gap findings pay out + auto-draft an
    amendment; hardening becomes a self-funding market. `POST /api/fleet/bounty`.
42. **Cross-org trust web** (`trustWeb.ts`) — counter-signed attestations form a verifiable trust
    passport partners/regulators accept. `POST /api/fleet/trust-web`.

## Amplifier layer VIII (20–500×+) — priced, learned, provable, federated, causal, oversight-ready

43. **Market economics** (`marketEconomics.ts`) — reputation staking + revenue-share settled by
    installer performance; best artifacts surface + their authors get paid. `POST /api/fleet/market-economics`.
44. **Admin decision model** (`decisionModel.ts`) — a learned logistic policy trained on the signed
    decision corpus, servable as a prediction capability. `GET /api/fleet/decision-model`.
45. **Constitution verifier** (`constitutionVerifier.ts`) — bounded model-checking proves the locked
    dimensions can't be breached; a bad amendment is caught before it ships. `GET /api/fleet/constitution-verify`.
46. **Multi-plane federation** (`federation.ts`) — cross-org threat signals elevate on ≥2 planes; an
    attack learned anywhere is defended everywhere. `POST /api/fleet/federation`.
47. **Causal treatment effect** (`treatmentEffect.ts`) — difference-in-differences estimates what a
    promotion actually CAUSED vs. controls. `POST /api/fleet/treatment-effect`.
48. **Regulator co-pilot lens** (`regulatorLens.ts`) — English compliance queries → filtered,
    PII-redacted, proof-linked, read-only answers. `POST /api/fleet/regulator-lens`.

## Production hardening (grounding the surface area)

- **Consolidation** (`shared.ts`) — one source of truth for the tier ordering, harm score, and
  amount bucketing; the three duplicated harm functions + two TIER_ORDER copies now import it.
- **Idempotent + compensable executors** (`executorRuntime.ts`) — `executeIdempotent` (at-most-once
  per action.id, failures retryable) + `runCompensable` (saga rollback of completed steps on a
  mid-plan failure). The prerequisite for any domain graduating to `auto`.
- **Shadow mode** (plane `PlaneConfig.shadowMode`, `FLEET_SHADOW_MODE` env) — govern + record what
  the plane WOULD do, never execute or bug a human. The safe onboarding week.
- **Eval harness** (`evalHarness.ts` → `GET /api/fleet/eval`) — precision/recall/F1 for the gate's
  auto-vs-human calls (false auto-runs are the safety metric) + the learned decision model, on a
  held-out slice of the real decision log.
- **Mission Control** (`web/pages/fleet.vue`) — one dashboard: KPI, human queue, incidents,
  treasury, safe-promotion batch, attestation.
- **Shadow emitter** (`apparently/scripts/fleet-shadow-emit.mjs`) — pushes Apparently's admin-board
  posts into the plane so the metrics reflect real traffic.

## Verification
- `cd packages/darwin-kernel && npx tsc --noEmit` → clean.
- `node --test --experimental-strip-types test/*.test.ts` → **154/154 pass**
  (fleetAdmin 15, fleetPlane 7, amplifiers 12+11+9+6+7+7+7+7, hardening 7, + original kernel suite).
- Live DB: `fleet_*` tables present on `eatfwdzfurujcuwlhdgj`; approver + demo approval seeded.
- 60 fleetAdmin kernel modules; 47 Orchestrator `/api/fleet/*` endpoints; Mission Control page; 2 scheduled tasks.
