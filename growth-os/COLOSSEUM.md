# The Marketing Colosseum — an evolutionary market for growth strategy

> Goal: outperform a million-person marketing org. Not by generating more, but by running a
> perpetual, self-scoring **market of competing strategies** that test live, grade themselves on
> profit with statistical rigor, remember everything, and transfer any win across all apps instantly.

The key difference from a normal "AI writes marketing" tool — and from a memo-drafting competition
(Apparently/Smarter style, where rival drafts compete and the best *argument* wins): here **every
proposal must reduce to a testable bet and win on live evidence, not rhetoric.** Strategists earn
reputation from realized outcomes. The arena is the Growth OS you already deployed.

## The cast: strategists as versioned capabilities

Each strategist is an agent persona with a distinct lens, stored as a capability (versioned, with a
policy + prompt). Seed roster (mutable — new ones are spawned by the loop):

- **Ogilvy** — research-led, credibility, long copy · **Bernbach** — creative disruption, emotion
- **Hopkins / Halbert / Kennedy** — direct-response, offer, urgency, relentless testing
- **Godin** — remarkable, permission, tribe · **Sinek** — purpose/"why"
- **Cialdini** — the 7 persuasion principles as testable levers
- **Ries & Trout** — positioning / category design · **Sharp (Ehrenberg-Bass)** — mental & physical
  availability, broad reach, distinctive assets
- **Brunson** — funnel/value-ladder · **PLG (Ellis/Chen)** — activation loops, viral coefficient
- **SEO/Programmatic** — corpus-fed page factories · **Community-led** · **Guerrilla/Wildcard** —
  invents unconventional mechanisms · **Superintelligence** — proposes novel AI-native tactics no
  human playbook contains

Each persona can specialize by objective: acquisition, activation, retention, or monetization.

## The arena: your deployed infra does the work

| Tournament step | Runs on |
|---|---|
| Propose | strategist agents (generation routed through `app_triage` = cheapest capable model) |
| Reduce to bets | `growth_segments` + `growth_arms` (each proposal = arms with a hypothesis + predicted lift) |
| Critique / red-team | multi-pass review (the Apparently/Smarter pattern), scored cheaply via triage |
| Allocate | portfolio bandit **across strategists** (who gets budget/traffic), UCB/Thompson |
| Test live | `pick_growth_arm` serves arms to real segment traffic |
| Measure | `growth_events` + `outcomes` (signups → paid → retained → profit) |
| Settle | `evaluate_growth_arms` (Wilson confidence gate) declares winners/losers |
| Score strategists | predicted-vs-realized lift + calibration (Brier) + $ generated |
| Bank the win | `promote_arm_to_play` → `instantiate_play` propagates it to every fitting app |
| Human gate & spend cap | `approvals` → Smarter; `provider_budgets` pattern per strategist |
| Claims integrity | policy constitution (`qc.ts`) + cite-check + Darwin attestation |

## The perpetual loop

1. **Draft.** For a target segment, each strategist submits proposals: a hypothesis, a predicted
   lift, a rationale (citing past plays, corpus authority, a competitor teardown), and the concrete
   arms to run.
2. **Debate.** A red-team agent + peer critique score each proposal for novelty, feasibility, risk,
   and expected value. Weak/duplicative proposals are cut. (This is your memo-competition mechanism —
   but the output is bets, not opinions.)
3. **Ante.** A bandit allocates the scarce resource (traffic/budget) across the surviving proposals —
   and across *strategists*, so proven strategists get more shots.
4. **Test.** Arms run live; evidence accrues in `growth_events`/`outcomes`.
5. **Settle.** The Wilson gate crowns winners and kills clear losers with statistical confidence.
6. **Score & evolve.** Update each strategist's **ELO + calibration**. Winners' tactics become plays
   (bankable everywhere). Losers are mutated (cross over winning traits) or retired. New strategists
   spawn. Budget reallocates toward the highest realized-ROI strategists.

Reputation is earned *live and continuously* — exactly "using the evidence to make their case as it
proceeds." A hype-heavy strategist with poor calibration loses budget automatically; a quiet one that
keeps beating its forecast gains autonomy (via the governance trust dial).

## Objective = profit, with retention weighted

The fitness function is not clicks. It's a composite over the funnel — signup → paid conversion →
retention → LTV/CAC → **profit** — so the system can't win by juicing top-of-funnel vanity. Separate
Colosseums run for **acquisition, activation, retention, and monetization**, because most of the
profit competitors leave on the table is in retention and expansion, not ad clicks.

## Why this beats 1,000,000 employees

A million people cannot: run millions of controlled experiments in parallel across every segment of
every app; remember every result forever; transfer a win to all apps in one call; grade themselves on
profit with confidence intervals; generate at near-zero marginal cost; and compound 24/7 without
politics. The Colosseum is not more headcount — it's an **evolutionary market with a live fitness
function**. Headcount adds linearly and forgets; this compounds and never forgets.

## Build order (next migration 0012 + a runner loop)

New tables (mirror what's already here): `growth_strategists` (persona, lens, objective, elo,
calibration, budget, status), `growth_proposals` (strategist, segment, hypothesis, predicted_lift,
rationale, critique_score, status), `growth_tournaments` (round, objective, allocations),
`growth_strategist_scores` (predicted vs realized, brier, pnl). Reuse `growth_arms/plays/events/
outcomes`. Add one orchestrator **loop** (the `loops` cadence table) that runs a round on schedule.
Surface the **leaderboard + pending go-live approvals** in Smarter.

---

## Further 20-500X (supportive / additive / novel), on top of the Colosseum

1. **Competitor-sensing agents (guerrilla).** Continuous teardown of rivals' funnels, ads, pricing,
   and SEO via Claude-in-Chrome; feed intel to strategists; auto-counter competitor moves.
2. **Synthetic-audience pre-testing.** Simulate segment personas with LLMs to pre-screen arms and
   kill obvious losers *before* spending real traffic — 10-100× cheaper exploration; only survivors
   go live.
3. **Internal prediction market among strategists (novel + on-brand).** Strategists wager reputation
   credits on each other's proposals; the market price becomes the allocation prior — wisdom-of-agents.
   This literally dogfoods Tomorrow's event-contract engine on your own growth.
4. **Message-market-fit mining.** Mine real customer language from Smarter inbound, reviews, and the
   corpus query log; generate copy in customers' own words; feed back what converts.
5. **Retention/expansion Colosseum.** Point the same machine at churn-save, onboarding activation, and
   upsell — where the profit actually is.
6. **Asset-level creative generation.** Auto-generate full landing pages / emails / ad variants as
   artifacts, each an arm; bandit + confidence gate pick winners; winners become plays.
7. **Pricing & packaging as an experiment surface.** Strategists test price points/bundles per segment
   (van Westendorp / willingness-to-pay), confidence-gated. (Apparently already prices dynamically.)
8. **Closed-loop, cross-app attribution via the identity graph.** Tie touch → signup → paid → retained
   across apps so the objective is true profit-per-touch, not last-click — this makes the whole
   Colosseum optimize the right thing.
9. **Self-discovering ICPs.** Cluster converting actors by behavior to *discover* micro-segments you
   never authored, then auto-spawn segments + strategists for them. The segmentation tree grows itself.
10. **Governance trust dial.** As a strategist's ELO + calibration rise, auto-grant more budget and
    lower the human-approval threshold; human attention concentrates only on novel/high-risk bets.
