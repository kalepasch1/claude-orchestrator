# apparently: exhaustive coverage + end-to-end autonomy audit — gaming then financial services, domestic + international

SUBMITTED-BY: kalepasch@gmail.com (operator decision 2026-08-04)

ACTIVATED 2026-08-04 by operator decision — the Wave-0 review gate this was held on now exists (commit a8ee6e3f, madeus.cc/waves).


ORIGINALLY-SUBMITTED-BY: kale@smrter.us (operator) 2026-07-28. Strategy: PORTFOLIO_STRATEGY_V2 Part 12.4c.

WORKFLOW: parallel_fleet

Objective: prove — as a living dashboard, not a claim — that Apparently can fully and exhaustively handle ALL of gaming from day 1, then all of regulated financial services, domestic + key international (UKGC, MGA, AGCO/Ontario, Gibraltar, Isle of Man, Curaçao; fin-services: federal + NY/CA/TX + key state regimes).

1. COVERAGE MATRIX: for each regulator × entity-type, enumerate EVERY interaction: licenses, applications, registrations, periodic filings, exams, memos, change-of-control, correspondence (NALs, extensions), remediation, ONGOING OBLIGATIONS (renewals, periodic reports with schedulers). Per cell: does a start-to-finish autonomous workflow exist once user inputs are collected? Status green/yellow/red; gaps AUTO-QUEUED as build tasks.
2. QA-BOT WALKTHROUGHS: bots execute every green workflow end-to-end on fixtures (input collection → generation → validation → submission artifact → obligation scheduling). Any failure flips the cell + queues the fix. Dead-code sweep: any workflow module not reachable from a matrix cell is flagged for deletion.
3. ONGOING-OBLIGATION VERIFICATION: every recurring obligation has a scheduler that fires (test with clock fixtures); renewal/report pipelines produce submission-ready artifacts.
4. UX PASS: per-vertical journey audit — a non-expert operator must be able to run each workflow from the OS with plain-language steps; department coordination routes through the embedded Smarter surfaces; friction findings queued.
5. PUBLISH: internal dashboard + a public trust surface ("what we complete autonomously today" — per-jurisdiction green-cell map, self-updating). This is marketing = the QA dashboard (12.8.2).
Proof: matrix populated for all covered regulators; ≥95% of green cells pass bot walkthroughs; schedulers fire on clock fixtures; dead-code report emitted; public map renders.
