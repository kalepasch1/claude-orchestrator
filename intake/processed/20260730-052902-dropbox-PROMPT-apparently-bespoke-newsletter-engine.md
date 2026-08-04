# Apparently — Bespoke Newsletter + Gated Report Engine (build now)

Operator directive 2026-07-30. Content flywheel with three tiers, all generated from the verdict-card
corpus and each client's own profile:

## Tiers
1. FREE public reports — marketing/power-demo (gauntlet-produced, commission + attorney gated,
   citation floor ≥10 overall / ≥5 per issue). Perpetually updated: each report carries the
   freshness contract ("valid as of corpus hash X") and re-renders when its authority chain changes.
2. GATED pre-drafted reports — the paid library; FREE to active subscription users.
3. NEWSLETTER incentive — subscribing to the Monday newsletter unlocks one typically-paid report.
   The subscribe surface explains exactly this value: "one premium report free, every analysis
   updated live, and a briefing written about YOUR business — not a firm blast."

## The differentiator: BESPOKE, not broadcast
Law-firm newsletters are generic. Ours is generated per subscriber from (a) their business profile
(vertical, jurisdictions, licenses held/pending, products), (b) the week's corpus changes (new
verdict cards, authority changes that touched THEIR cards, enforcement actions in THEIR states),
(c) their open compliance gaps. Structure per issue: "What changed for you this week" → "What it
means for [company]" → "What we'd do before Friday" → one featured deep-dive. If nothing material
changed for a subscriber, SAY SO in one paragraph — a short honest issue beats padded relevance.

## Mechanics
- Monday 06:00 ET send; per-subscriber render pipeline (subscriber profile × weekly corpus diff).
- Every claim cites; every issue carries the disclaimer + unsubscribe + "book independent counsel".
- Track which sections drive opens/clicks per subscriber and let the renderer learn per-client
  emphasis (their idiom: exec summary vs technical depth).
- 50-500X hooks: (1) the newsletter IS a sample of the paid product — each item links to the full
  gated report; (2) "your competitors' regulatory week" section from public-record data only;
  (3) quarterly auto-generated "your regulatory posture, trended" mini-report per subscriber.
- Reuse Apparently's email infra + existing report/blog tables; RLS default-deny; no cross-client
  leakage in any render path (test for it explicitly).
