# Policy Waterfall Engine — every approved change ripples through every governing document (build now)

Operator directive 2026-07-30. When ANY trigger activity is approved (a code change, a filing, a
document edit, an email commitment, a new product mechanic), every affected internal governing
text — policies, procedures, rulebooks, compliance manuals, AML program docs, RG program docs,
terms, playbooks — must be identified, redlined, routed for the RIGHT department's approval, and
updated, until the whole set is consistent and the audit table holds the complete chain
(approvers, explanations, timestamps). Nothing governs stale.

## Reuse first (both engines already exist in pieces — compose, don't reinvent)
- Tomorrow's clause dependency graph + BFS impact traversal (clauseDependencyGraph.ts) and the
  war-room approval/consent machinery = the ripple + approval pattern.
- Apparently's GRC module (migration 343) + compliance passport + audit tables = the document
  registry + audit substrate.
- The verdict-card authority-chain staleness model = the SAME event-driven invalidation, applied
  to INTERNAL documents: each policy carries a dependency manifest (which regulations, which
  internal docs, which product mechanics it depends on).

## The waterfall
1. REGISTRY: every governing document registered with a dependency manifest (auto-drafted by
   ingestion on first pass; maintained by the engine thereafter).
2. TRIGGER: an approved change emits its impact dimensions (already in the Foulkon gradient) ->
   the graph resolves the affected document set (transitively — a policy change can implicate
   further policies; iterate until closure).
3. REDLINE: for each affected doc, auto-draft the amendment (gauntlet-reviewed for
   legal/compliance-class docs; cheap tier for procedural text), with a WHY memo linking back to
   the trigger.
4. ROUTE: each amendment routes to its OWNING department's approval queue per the permissions
   framework + that department's mini-constitution (quorum, thresholds). Attorney-class docs ->
   the 5.8b queue.
5. CLOSE: the waterfall is OPEN until every amendment is approved/applied/logged; the progress
   console shows waterfall status per trigger ("7 of 9 documents updated; AML manual pending
   compliance approval, 2 days"). Stale waterfalls escalate on SLA.
6. AUDIT: one chain per waterfall: trigger -> affected set -> each redline -> each approver ->
   each explanation -> timing. Exportable (the examiner-ready format the evidence locker uses).

## 50-500X hooks
- CONSISTENCY SENTINEL: continuously diff actual practice (code behavior, filed positions,
  live product mechanics) against what the governing documents SAY — the NJ exam finding
  "internal controls vs. actual practice drift" is the #2 statistical flag in our own Monte-Carlo;
  this engine is the standing cure, and "zero drift" becomes a marketable exam posture.
- PRE-APPROVAL PREVIEW: at decision time, the gradient option shows its waterfall footprint
  ("choosing this updates 6 documents across 3 departments") — cost-of-change made visible
  BEFORE the choice.
- REGULATOR-CHANGE INGESTION: external events (rule changes from the monitored feeds) enter the
  SAME waterfall as internal triggers — one engine for "we changed" and "the law changed".
- The waterfall ledger doubles as the compliance-history product surface (regulator portal
  evidence: "every policy update, its trigger, and its approver, for three years").
