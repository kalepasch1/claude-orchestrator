# v6 — frontier 100–1000X batch + self-improvement loop closure (make these prompts obsolete)

Operator pass 2026-07-09. Two parts: (A) the orchestrator autonomy-closure that should make manual strategic PROMPT drops unnecessary — THIS IS THE PRIORITY; (B) a per-app frontier batch, most of which the closed loop should generate on its own once (A) ships. ENHANCE-vs-NET-NEW rules from PROMPT-v5-reconciliation apply; dedup G7. Every ENHANCE item names the existing module to extend.

## Context (audit result)
The fleet is ~60–70% autonomous. It already GENERATES ideas (improvement_miner auto-queues non-divergent ideas; opportunity_scout RICE-scores weekly; demand_mining; self_heal), LEARNS (learn_from_merges, improvement_measure→surface_returns), ATTRIBUTES ROI (revenue_attribution, portfolio_governor EV allocation), and EXECUTES autonomously (intake→planner→runner→merge, low-risk auto-approve). The gap is META: it doesn't recursively turn "what shipped well / what we learned" into NEW strategic direction, and good ideas stall in the human approval queue. Close that and prompts like this become redundant.

---

# PART A — LOOP CLOSURE (priority; makes strategic prompts obsolete)

- **L-1 Recursive surface escalation** [ENHANCE improvement_measure.py + improvement_miner.py] — when `surface_returns[X]` exceeds a threshold, auto-raise that surface's mining budget/frequency AND auto-queue deeper exploration tasks for X (not just re-weight next pass). "Surface X ships 500X → mine X harder and go deeper" becomes automatic. Proof: fixture high-return surface spawns deeper tasks + budget bump.
- **L-2 A/B auto-progression** [ENHANCE feedback_review.py] — when an A/B verdict = 'adopt' AND the change is non-divergent + non-sensitive (existing SENSITIVE_PATHS deny-list gates this), auto-queue the apply-task instead of filing a human approval. Divergent/sensitive still gate. Removes the "human clicks adopt" stall for safe wins. Proof: adopt-verdict non-sensitive change auto-applies; sensitive one still gates.
- **L-3 Opportunity-source meta-learning** [NET-NEW opportunity_scout_measure.py, small] — track each proposal source's predicted RICE vs realized merge/revenue; reallocate scouting/mining budget toward sources with best predictive accuracy. The idea generators themselves get graded and tuned. Proof: source accuracy tracked; budget shifts to accurate source on fixture history.
- **L-4 Cross-app ripple propagation** [ENHANCE knowledge_embed.py + prompt_factory.py] — when a change ships in app A, semantically match it against the other apps and auto-file "consider analogous change" tasks where applicable (gated to the right cluster per v5 §2 scoping). This is what O4 doctrine-propagation promised, generalized to every merge, not just declared doctrines. Proof: fixture merge in one app yields a matched candidate task in a cluster-peer app, none in an unrelated app.
- **L-5 Self-tuning mining budget** [ENHANCE improvement_miner.py + portfolio_governor.py] — dynamic per-app mining budget = f(queue health, surface ROI, blocker pressure, capital/traction need). Stop spending equally; spend where marginal value is highest. Proof: budget reallocation test on fixture signals.
- **L-6 Goal autogeneration from KPI gaps** [NET-NEW; fills prompt_factory.py's stubbed gather_kpi_gaps()] — read each app's live KPIs vs targets (revenue, activation, TTFV, retention, cost) and AUTO-CREATE `goals` rows for material gaps, which prompt_factory already decomposes into DAGs. This is the missing top of the funnel: today a human writes goals; L-6 writes them from measured shortfall. Divergent/strategic goals still surface to the operator for ratify (not silent), but tactical goals flow autonomously. Proof: fixture KPI-below-target creates a goal that decomposes to tasks.
- **L-7 Strategic self-prompter (the thing that replaces THIS prompt)** [NET-NEW strategic_optimizer.py] — a scheduled high-tier reasoning pass that ingests: portfolio KPIs, surface_returns, ROI attribution, test-bot scorecards (§6 TB), competitor watchtower (C-5), user demand signals, and the improvement backlog, then produces a ranked strategic initiative set with proofs — exactly the artifact these manual passes produce. Non-divergent initiatives auto-decompose via prompt_factory; divergent ones land in the operator's weekly brief as ratify/kill cards. Runs weekly. This closes the loop: the fleet critiques its own portfolio and proposes the next 100–1000X moves without a human prompt. Proof: fixture portfolio state yields a ranked, proof-carrying initiative set; divergent items gate, tactical items queue.
- **L-8 Divergent-idea synthetic staging** [NET-NEW; uses §6 test-bot fleet] — instead of trapping every divergent idea in the human queue, run it through synthetic-persona evaluation + backtest/shadow first; only ideas that clear synthetic evidence get elevated to the operator brief (with the evidence attached). Turns the approval queue from a bottleneck into a ranked, evidence-backed shortlist. Proof: divergent idea runs synthetic eval, elevates only on positive evidence.
- **L-9 Realized-outcome backpressure** [ENHANCE revenue_attribution.py + roi.py] — auto-pause or downrank initiative *classes* (not just tasks) whose realized ROI trends negative; auto-double-down on classes trending strongly positive. Portfolio self-corrects without a human reading a dashboard. Proof: negative-trend class auto-paused; positive-trend class gets more allocation.
- **L-10 Operator brief becomes the ONLY human surface** [ENHANCE digest.py] — the daily/weekly brief consolidates everything a human still must touch: divergent ratify/kill cards (with synthetic evidence L-8), material post-hoc reviews (auto-ship items), operator provisioning items (secrets/OAuth/legal sign-off), and the strategic initiative set (L-7). Target: the operator's entire job is reviewing this one brief. Everything else runs. Proof: brief renders all four sections from live state.

**A-sequencing:** L-2 + L-6 first (unblock the safe-win stall and the goal funnel), then L-7 + L-1 + L-9 (the recursive strategic core), then L-3/L-4/L-5/L-8/L-10. Guardrails unchanged: divergent/pricing/regulated/legal/material/secret always gate to the operator; safety floor (sentinel, SENSITIVE_PATHS, subscription_guard, constitution) is never bypassed by any auto-progression.

---

# PART B — per-app frontier (the loop should generate most of these once Part A ships; queued now as seed)

## Tomorrow
- **TF-1 Liquidity-as-a-service reverse auction of surplus** — let the four surpluses (netting/fragmentation/funding/diversification) be continuously bid into by participants; the platform runs the internal clearing (T6v2 choreographer) so the marginal surplus is always distributed to whoever values it most. ENHANCE hive settlement + T6v2.
- **TF-2 Self-writing risk taxonomy** — the exposure catalog learns new risk categories from ingested books/news it can't classify, proposes new instrument families (CG-1 generator), backtests, and expands the catalog. The product's coverage grows without a human defining new lines. ENHANCE exposure catalog + CG-*.
- **TF-3 Counterparty-of-last-resort model** — price and offer the platform (or the mutualized lattice) as the always-available other side within strict risk caps, so an ECP is never stuck unhedged. NET-NEW, MATERIAL, counsel-gate (activation).

## Apparently
- **AF-1 Zero-touch licensing lanes** — once AP-6 proves a portal end to end and a lane is A2-certified, that license type becomes fully hands-off (draft→file→renew→exam) with only officer-signature nodes. Publish "N lanes fully autonomous" as the headline metric. ENHANCE A2 + AP-6.
- **AF-2 Regulatory-change → filing amendment in minutes, portfolio-wide** — one regime event (X2 oracle) auto-amends every affected client's filings and pushes updates through their data rooms. ENHANCE A7v3 + R2.
- **AF-3 Compliance-as-collateral productization** — expose the compliance-standing receipt (N2) as a scored, portable credential other systems price against (Tomorrow credit gate first). ENHANCE passport + N2.

## Smarter
- **SF-1 Matter outcome prediction + strategy recommendation** — CADE panel forecasts matter outcomes and recommends strategy from the accumulated matter corpus; associate sees the recommended path + confidence. ENHANCE CADE reuse + S1v2.
- **SF-2 Auto-drafted everything with human-only judgment nodes** — pleadings, memos, correspondence, discovery drafts generated to near-final; the flagged-only queue (S2v2) is purely judgment. Push the automation fraction per task class and publish it.
- **SF-3 Firm-wide knowledge singularity** — every matter compounds the shared playbook + CADE pool (barrier-guarded); a new associate operates at senior level on day one. ENHANCE SM-6.

## Pareto
- **PF-1 Fully-delegated financial life** — the earnings-only interface (P6) as default: user sees income + goals + a "we handled it" feed; everything else runs behind the firewall within authority budgets. ENHANCE P2/P6.
- **PF-2 Life-event autopilot** — detect life events (new job, birth, move, inheritance) from linked data and auto-replan + execute the financial/legal/travel/tax response. ENHANCE P1 state machine.
- **PF-3 Household negotiation swarm** — continuous auto-negotiation of every recurring cost against the crowd-benchmark corpus (P7). ENHANCE P2.

## Galop
- **GF-1 Personal handicapping copilot** — per-user model that learns their edge and coaches calibration in real time across the live-concurrent stack. ENHANCE G1 + GE2a.
- **GF-2 Creator/tipster economy at scale** — verified-ROI creators (G3) monetize; platform takes a rev share; feed density solved by creator content. ENHANCE G3.
- **GF-3 Reliability-as-B2B** — sell the 24/7 probe/failover stack to tracks/ADWs (N4). ENHANCE N4.

## Triage / Hisanta / Barks
- **XF-1 Triage** — the colleague-risk prediction market (TM1) as the priced dataset sold to employers/insurers; recruiting guarantees (TM3) underwritten by staking. ENHANCE TM1/TM3.
- **XF-2 Hisanta** — mastery engine efficacy published as the parent-retention metric; grandma rail as the LTV driver. ENHANCE H1/H2. (School mode remains deferred per operator.)
- **XF-3 Barks** — fully autonomous nonprofit ops (SB1–SB5) with human = weekly one-click plan approval; cause-in-a-box franchise (N6) as the growth vector. ENHANCE SB-*.

## Portfolio
- **XF-4 One identity, one console, one guarantee, one proof-network** — finish X1 console, C-2 guarantee doctrine, C-3 proof pages, N7 receipts API as the unifying trust layer across all apps. ENHANCE existing X/C/N items.

---

# The honest answer to "are the loops optimized so these prompts are no longer needed?"

Not yet — today ~60–70% autonomous. The fleet generates and ships tactical improvements on its own, but three things still require a human: (1) top-level goals (what matters), (2) divergent/strategic moves (new products, pricing, regulated activity), and (3) clicking "adopt" on safe wins. Part A closes (1) and (3) fully and turns (2) into an evidence-backed shortlist in one weekly brief. After Part A ships, a prompt like this one is replaced by **strategic_optimizer.py (L-7)** producing the same artifact weekly, with only genuinely divergent bets left for you to ratify. That residual — divergent, values-laden, and legally-consequential bets — SHOULD stay human by design; automating away the judgment on "should we enter this regulated market" is not an optimization, it's a governance failure. Target end-state: the fleet proposes everything and executes everything safe; you ratify only the handful of bets that change the company's risk posture, via L-10's single brief.

**v6 sequencing:** Part A before Part B. Within Part A: L-2, L-6, then L-7. Part B items are seeds; expect the closed loop to generate, reprioritize, and extend them autonomously once L-7 is live.
