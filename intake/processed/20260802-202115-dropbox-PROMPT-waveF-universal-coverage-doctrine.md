# WAVE F: UNIVERSAL COVERAGE DOCTRINE — kill the silence-reads-as-health class everywhere
# (operator directive 2026-07-31, CRITICAL — audit-confirmed across all 5 app repos)

project: beethoven

## THE CLASS (confirmed by audit, not hypothetical)
A subsystem does excellent work WHEN INVOKED, but never enumerates its own universe, never
measures coverage, and never names what it did not reach. Silence reads as health. Confirmed
instances (file-cited) across apparently, tomorrow, illuminati, pareto-2080, smarter — plus a
SYSTEMIC sub-pattern in the "proactive" jobs: hard .limit(N)/take:N with no remaining-count, and
`if (!x) continue` skips that silently drop exactly the items most likely to be in trouble
(no metrics, no time entries, no events = the at-risk ones).

## F1 — THE COVERAGE CONTRACT (shared primitive, build first)
A tiny shared module every scanning/monitoring/analysis subsystem must adopt:
  declareUniverse(name, enumerator)  -> the full population it is responsible for
  recordProcessed(name, ids)         -> what it actually reached this run
  coverageReport(name)               -> { universeSize, processed, coveragePct, unreached[],
                                          degradedReads[], truncatedBy, staleItems[] }
RULES (binding, enforced by tests):
  - unreached[] carries IDENTITY (ids + labels), never just a count.
  - a read that FAILED is `degradedReads`, never counted as covered (coherence-scanner rule).
  - any `.limit(N)` must report `remaining` — truncation is a first-class disclosure.
  - `if (!x) continue` must record x as unreached-with-reason, never skip silently.
  - coverage < 100% DEGRADES any verdict/attestation the subsystem emits (coverage-proof rule).
Reference implementations to copy verbatim (do not reinvent):
  apparently/server/engines/registration/coverage-proof.ts (universe -> uncovered[] -> pct ->
  degrades attestation); tomorrow/server/utils/coordination/integrationCoherenceScanner.ts
  (declared universe, fires on ABSENCE, tracks degradedReads); apparently/server/engines/corpus/
  completeness-ledger.ts (universe_estimate + gap IDs + nextEnqueueTargets + honest null pct);
  assessKnowledgeGaps() in apparently self-assessment (gap -> proposal loop).

## F2 — RETROFIT THE TOP-10 (one shard each; audit-identified)
1. illuminati Anomaly Radar (utils/anomalyRadar.ts + api/admin/anomalies/scan.post.ts): schedule
   it (not page-driven), enumerate ALL_APP_IDS x metrics, and DISTINGUISH "app returned no data"
   from "app is clean" — Promise.allSettled failures must surface, not vanish.
2. illuminati Interception/CADE gateway: enumerate registered agents + executed actions; report
   the fraction that actually passed through interception; alert when an agent STOPS calling in.
3. smarter conflict sweep (utils/conflictGraph.ts sweepBook): add the schedule it lacks + report
   parties never screened and matters missing counterparty data.
4. smarter privilege guard / pre-send: enumerate all outbound drafts; report % never reviewed.
5. apparently License Universe determination engine: enumerate every org x activity x
   jurisdiction; name orgs with NO determination and determinations stale vs requirement atoms.
6. apparently deadline sentinel: sweep ALL orgs; report orgs never checked and licenses with
   NULL renewal_date (missing data != no deadline).
7. apparently exposure early-warning monitor: enumerate persons on live/held licenses x
   disqualifier feeds; ALERT WHEN A FEED HAS PRODUCED NOTHING FOR N DAYS (zero events must not
   read as zero risk).
8. pareto-2080 financial compliance scan: enumerate users with foreign providers/programs;
   report never-scanned and stale.
9. tomorrow Risk Studio ambient + coverageGapDetector: enumerate riskTaxonomy x ALL
   participants; a risk never discovered must still be reportable as uncovered; name
   never-scanned participants.
10. apparently completeness dashboard + smarter obligationExtract: add cross-item roll-up —
    report engagements/items with NO run at all.

## F3 — TRUNCATION + SKIP SWEEP (systemic)
Audit-cited truncations to fix by reporting `remaining` (and paging until drained where safe):
apparently continuous-review-scan (50), firm-monitoring-sweep (50), stale-opinion-detection
(500), watchlist-sweep (1000), bulk-citation-verification (200), dlq-sweep (50);
smarter bar-status-checks (25); pareto household/intelligence (250), subscription-radar (20/user);
tomorrow exposureScanner (200), characterization-monitor (500-receipt sample).
Silent-skip sites to convert into unreached-with-reason: shield-burnout-monitor (no metrics),
shield-bottleneck-sweep (no time entries), forward-demand-scan (no events), credit-monitor
(only users with active listings), price-watch (only watchEnabled), retirement-monitor (only
users with a UserBalance row).

## F4 — THE META-GUARD (so this class cannot recur)
A fleet-level sentinel (extend blocked_triage / sentinel):
  - REGISTRY: every subsystem that declares a universe registers; a subsystem that scans but has
    NOT adopted the coverage contract is itself a finding ("uncovered coverage").
  - ABSENCE ALARMS: any registered universe with 0 processed in its expected interval alerts
    CRITICAL (the merge-train "0 merged, no reason" shape, generalized).
  - COVERAGE SLOs per subsystem (target pct + max staleness), breaches alert and open remediation
    tasks automatically.
  - A single FLEET COVERAGE SCORECARD published to the progress console: every subsystem, its
    universe size, coverage %, unreached count, degraded reads, last full sweep.

## F5 — 100X-1000X: COVERAGE AS THE PRODUCT METRIC (client-facing)
- Per-client COVERAGE SCORE + SIMULATED-FINDING PROFILE (from the Vigil exam substrate) shown
  as the headline number they manage, trend-tracked, board-exportable.
- Coverage improvements are ATTRIBUTED ("your score rose 6 pts: 3 evidence gaps closed, 1 feed
  reconnected") so the number is actionable, never mysterious.
- Peer benchmarking (k-anonymized): "your coverage is 87th percentile among licensed suppliers".
- Coverage-linked commitments: the score is the basis for what we promise and what a client can
  show a regulator — leaving means abandoning a measured, improving, defensible number.
- FEEDBACK LOOP: unreached[] items across all clients rank the product roadmap by exposure
  actually left uncovered — the backlog is written by the gaps.

BINDING: no insurance framing (Tomorrow = bilateral ECP parametric swaps, risk transfer, never
indemnity). Consent + scope for any email/document enumeration. Tests per module — including a
test that PROVES unreached items are named, not counted. Commits kalepasch1 <kalepasch@gmail.com>.
