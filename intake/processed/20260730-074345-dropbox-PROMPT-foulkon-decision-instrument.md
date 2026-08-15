# Foulkon — The Decision Instrument (full implementation)

Operator directive 2026-07-30. The risk gradient graduates from advisory to a COMPLETE DECISION
INSTRUMENT: every material steering option prices its three exits — **ACCEPT** (what not acting
costs, probabilistically: Vigil enforcement lens), **REMEDIATE** (1-click filing/registration/
report: activation), **TRANSFER** (Tomorrow parametric hedge: premium vs. covered loss, 1-click,
eligibility-gated) — and every gradient is fully explainable to every team via the dossier.
The comparison between the three exits becomes ARITHMETIC displayed to the user, not judgment.

The schema contract is ALREADY SHIPPED in illuminati `server/utils/rapidGradient.ts`
(`GradientOption.activation` / `.enforcement` / `.transfer`, `EnforcementSpec`, `TransferSpec`) —
build to it exactly; do not fork it. Companion bridge builds are queued separately
(`PROMPT-tomorrow-foulkon-hedge-bridge.md`, `PROMPT-vigil-foulkon-enforcement-bridge.md`); this
prompt owns the UI + orchestration + learning layers.

## Workstreams (decompose per section; each independently mergeable)

### W1 — Streaming gradient card UI (the hook surface)
The one-screen gradient card: top-7 as horizontal risk bars (high→low, scored), seat-consensus
badges, red-team chips, pause-scope chip ("holding 2 files; everything else continues"),
`extended_options` behind an expand control. STREAMING contract: T0 partial renders instantly →
deterministic seat candidates <1ms → LLM options appear as seats land → tournament re-ranks live.
The user watches the swarm think; never a spinner. Shareable: one click exports the card as a
clean image/link (the Slack screenshot growth loop — make the export beautiful, branded, and
containing nothing confidential by default).

### W2 — Dossier display (the trust surface)
Beautiful, hyper-organized rendering over `POST /api/cade/explain` (JSON is already hierarchical):
§1 conclusion + what enables it; §2 evidence with one-click card dive-deeper (`/api/cade/card/:id`);
§3 per-option risk-source tables with KEY VERBATIM MATERIAL visually highlighted (the red-team
attack, named authorities, binding conditions — quote-styled, source-chipped). Audience toggle
(legal/compliance/engineering/executive) re-renders via the idiom layer; `raw` is instant. Inline
"ask about this" prompting on every section (prefilled with the artifact ID + section context).
Deep-pass jobs render the live progress tracker (stage, %, ETA, predicted-value) from
`GET /api/cade/gradient-job/:id`.

### W3 — Speculative pre-gradient + session memory (perceived latency → 0)
(a) Watch the working diff; when a decision point is PREDICTED (new payment/wallet/promo/AI-
decisioning touchpoint appearing in a branch), fire `mode:'instant'` then `complete` in the
background so the tribunal has already run when the developer arrives. (b) Session memory:
within a session, decisions similar to a prior tribunal (similarity over decision text + scope)
reuse and DELTA the prior result instead of re-convening; show "updated from your 14:02 gradient".

### W4 — Outcome learning
Record option-selected vs. option-recommended per gradient; disagreement patterns feed (a) seat
weighting (a seat whose options are never chosen argues worse than one whose are), (b) the corpus
docket (systematic disagreement on a question class = re-debate it), (c) a per-company risk-
appetite profile that tunes the recommended_index — the tribunal learns the company's appetite
without being told.

### W5 — The triad comparison row
When enforcement + transfer data are present (bridges), render the three-exit arithmetic per
option: ACCEPT expected cost (p_action × severity band) vs REMEDIATE cost+time (activation) vs
TRANSFER premium (hedge). One row, three buttons, each 1-click (filing → activation flow; hedge →
eligibility-gated Tomorrow flow; accept → documented acceptance with sign-off + revisit date
logged to the audit chain — acceptance is a DECISION with a name on it, never a default).

## Constraints
- All display surfaces consume the existing endpoints; no schema forks.
- Confidential-by-default exports; disclaimer on every surface; not legal advice.
- Accept-path sign-off is mandatory and logged (an un-actioned high-risk option auto-revisits).
- QA: vitest/playwright per workstream; the streaming card must render with 0, 1, and 14 options.
