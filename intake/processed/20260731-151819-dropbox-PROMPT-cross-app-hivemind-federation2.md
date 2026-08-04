# Cross-App Hivemind Federation — one market-shaped intelligence (operator, 2026-07-31, redrop)

project: tomorrow

(Prior drop was skipped: planner emitted unregistered project 'claude-orchestrator'. This work
builds primarily in the TOMORROW repo — the spine reuses tomorrow/server/utils/ai/federatedRiskIntel.ts —
with typed cross-app contracts consumed by apparently, vigil, and illuminati via their own queued shards.)

Tomorrow's relationship agents, Apparently's capability bots, and Vigil's enforcement sentinels hold
half-signals about the SAME entities. BUILD the federated identity spine that joins them:
1. SPINE (in tomorrow): privacy-preserving entity resolution across apps (e-DP noise, k>=3 anonymity —
   REUSE server/utils/ai/federatedRiskIntel.ts + privacyBudget; do not rebuild). Entities keyed by
   salted stable identifiers; no raw portfolio/PII leaves any app boundary. Expose as an HMAC S2S
   API (mirror the PLOEH/gaming _s2s.ts pattern) so the other apps consume it server-to-server.
2. SIGNAL FLOW (automatic): Apparently contract-risk extraction -> Tomorrow IOI demand signal ->
   Vigil exposure prior -> back into Foulkon EnforcementSpec expected_loss_usd. Each hop is a
   typed, versioned event; define the shared Zod/TS contract package in this repo.
3. 50-500X EXTENSIONS (build all):
   a. SIGNED CROSS-APP ATTESTATIONS: wrap federated signals in C1 verifiable proofs
      (server/utils/proof/verifiableProof.ts) so each app verifies provenance OFFLINE.
   b. LIVE HEDGE JOIN: gradient displays join the federated demand/coverage signal to real-time
      Adaptive Perpetual Line guide prices — Hedge & Proceed reflects the WHOLE network's standing
      book, not one app's view.
   c. CONSENT + PURPOSE-LIMITATION LEDGER: per-app opt-in scopes, append-only; every federated
      query logs purpose + scope (privacy-audit-ready).
   d. NETWORK FLYWHEEL METRIC: per-app + combined "federation dividend" (signal lift vs siloed
      baseline) published to the progress console.
POSTURE: multilateral = discovery/optimization only; execution stays named bilateral (N5/N6).
All commits kalepasch1 <kalepasch@gmail.com>.
