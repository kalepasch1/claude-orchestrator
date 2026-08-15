# tomorrow: Anticipation Layer × War Room fusion — the clairvoyant negotiation room

SUBMITTED-BY: kale@smrter.us (operator) 2026-07-28. Strategy: PORTFOLIO_STRATEGY_V2 Part 13.5 + 13.6 (beethoven repo root — READ BOTH FIRST). War room code lives in this repo (server/utils/warRoom/* + /api/firm/rooms/* + /api/warRoom/*). Coordinate file scopes with the in-flight tomorrow wave (credit/swap surfaces — mostly disjoint from warRoom/*).

WORKFLOW: parallel_fleet

Objective: fuse the Anticipation Layer (standing unprompted swarms; "user only steers novelty") with the war room's existing intelligence so every negotiation room becomes clairvoyant. The war room ALREADY has the primitives — behaviorFingerprint, responseTimingIntel, clauseDependencyGraph, warGaming, replyStrategies, playbookEngine, sentimentTimeline, behavioralPredictionModel — this workstream COMPOSES them into always-on anticipatory capabilities. Reuse, never rebuild.

## 1. Room-native Counterparty Anticipator (13.6.1)
- Before any document/reply leaves a room: simulate THIS counterparty's response from their live fingerprint (past redlines, concession patterns, timing, tone, walk-away history across all platform negotiations) — reuse behaviorFingerprint + counterpartyGraphIntel + negotiationPatterns + responsePrediction. Produce: predicted redline/objections/asks, pre-hardened draft variants, and warGaming scores per variant. Render as a pre-send panel with adopt/compare actions; log to the room ledger (item 5).
- Proof: fixture room with a seeded fingerprint yields a specific (not generic) predicted redline; pre-hardened variant scores higher in warGaming; ledger entry written.

## 2. Downstream-Consequence on the clause graph (13.6.2)
- Every clause edit in a room instantly evaluates impacts across: the room's clauseDependencyGraph, sibling agreements in the matter, and living-memo dependencies (Apparently S2S where linked). Findings render inline in the room (the consistency-check machinery exists — make it CONTINUOUS + edit-triggered, not on-demand).
- Proof: a fixture edit to a defined term flags the dependent clause + a sibling doc + a linked memo within one event cycle.

## 3. Adversarial deep-cite — verify THEIR citations (13.6.3)
- On every inbound counterparty document (email bridge/channel ingest/portal): pull each cited authority and verify the proposition it's cited for (deep verification, not format checks — reuse citation infra + corpus fetch). Mis-citations surface as LEVERAGE cards in the room ("their §4.2 authority does not support the stated proposition — draft response attached") with the pre-drafted response.
- Proof: fixture inbound doc with a seeded mis-citation produces a leverage card + draft response; correctly-cited fixture produces none.

## 4. The Overnight War Room (13.6.4)
- Nightly batch per ACTIVE room: run the full anticipatory suite (items 1-3 + CADE risk pass + formatting via Smarter S2S + bolstering) and deliver a MORNING BRIEF per room: what moved; what their silence means (responseTimingIntel); predicted next moves with probabilities (behavioralPredictionModel); pre-drafted responses per branch; weaknesses found in their latest documents; and the 1-3 judgment calls needing the human (CADE novelty detector routes ONLY genuine-judgment items, as decisions-with-options). Beautiful, scannable brief (this is the product promise: "everything we strengthened, verified, flagged, and prepared while you slept — N items need your judgment").
- Cron dual-registered (vercel.json + nuxt scheduledTasks) per repo convention; per-room opt-out config.
- Proof: fixture room generates a complete brief from seeded overnight events; novelty router sends exactly the seeded-novel item to the judgment list; cron registered both places.

## 5. The room "work done for you" ledger (13.6.5)
- Every unprompted anticipatory action logs to a per-room ledger visible to the negotiation team AND (configurably) the client — the war room becomes a demonstrable value engine. Ledger entries: action, trigger, artifact link, time saved estimate. Roll-up panel in the room UI + a client-shareable summary.
- Proof: ledger accumulates across items 1-4 on fixtures; client-share view renders with internal-only entries excluded.

## Constraints
- Compose the existing warRoom engines — do not duplicate them (the coherence bot will flag drift). Non-material surfaces except S2S/live-money touches (stamp those). Posture greps stay clean; repo CLAUDE.md conventions; SFC compiles; tests per engine touched.
