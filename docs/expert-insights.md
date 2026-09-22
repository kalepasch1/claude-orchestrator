# Expert insights

_How the standing expert panels find regulatory gaps and innovation pathways, how what they
conclude becomes steering, and how every model output is measured. Each claim names the
module that implements it._

## What an audit on 2026-09-21 found

| | Finding |
|---|---|
| Verdict cards | 352 cards, median 1,180 characters, every one with citations, dissent and "flips if". Good work — read by exactly two modules. Nothing a panel concluded reached a coder prompt, a memo or the owner. |
| Docket | 1,874 questions, 1,522 pending, 2–7 answered a day against intake spikes of 100 a day. 55% marked "high" (three generators hard-coded it). Six gaming and crypto personas in about a third of questions. 2.6% with any innovation, cross-industry or opportunity framing. 87 of 150 lens × risk × vertical cells empty; 6 cross-industry and 13 red-team questions in total. |
| Picker | `priority.asc,created_at.asc` on a TEXT column is alphabetical (high, low, medium), oldest first. The `data` vertical (13 pending) was unreachable behind 1,022 old "high" questions. |
| Local models (Ollama / exo) | 1,000 consecutive `app_operations` rows: `quality_score` and `verdict` NULL on all of them, 97% `task_class='unknown'` under `operation='completion'`, 96% zero-latency cache replays. Memo drafts with `[GC's Name]` left in; verdicts reading `conditional / 7 / 8` again and again. |
| Posted rows | 27% of the latest 300 docket questions fail basic admission (75 name no authority or regulator, 6 carry an unfilled placeholder). Verdict cards grade 0.99. |

## What runs now

**`runner/docket_matrix.py` — the docket as a matrix.** Every question has coordinates:
a lens (`regulatory_gap`, `enforcement_trend`, `cross_industry_analog`, `innovation_pathway`,
`red_team`, `opportunity`), a risk band (`existential`, `high`, `medium`, `low`, `upside`) and
a vertical. `classify()` places the existing questions with keywords alone; `coverage()`
counts cells; `next_cells()` names the emptiest, with `ORCH_DOCKET_INNOVATION_SHARE` (0.4)
of them guaranteed to the three innovation lenses; `generate()` asks a costless model for
candidates for exactly those cells — the cross-industry lens must name ONE donor industry
and its mechanism (aviation SMS, pharma ALCOA+, bank model-risk SR 11-7, nuclear
defence-in-depth, medical-device vigilance, DSMBs, PCI DSS, HACCP, ISO 26262, Reg SCI, SOX,
ORSA) — and admits only what survives `grade_question()`: a real question, an authority
named, no placeholder, no chat boilerplate, not a near-duplicate (Jaccard ≥ 0.6) of anything
on the docket. Priority is earned from the risk band (`calibrated_priority`); "high" is
refused once it exceeds `ORCH_DOCKET_MAX_HIGH_SHARE` (0.3) of the pending docket unless the
band is existential. `ambiguity_miner` and `reg_opportunity_scan` no longer stamp "high".

**`docket_matrix.pick()` — what the panel answers next.** Value = risk weight × lens weight
× a boost for verticals nobody has answered for, matrix-origin and stale cards slightly
ahead; verticals take turns. `legal_docket._stale_or_unanswered` uses it
(`ORCH_DOCKET_VALUE_RANK`, default on; the legacy sort is the fallback).
`legal_docket.run()` tops the matrix up first (`ORCH_DOCKET_MATRIX_TOPUP`, 4 cells).

**`runner/steering_insights.py` — verdict cards become steering.** `distill(card)` needs no
model: `conditions` → `action` insights (imperatives only), `flips_if` → `tripwire`
("Watch for: …"), low-confidence `assumptions` → `assumption`, `unsettled` → `gap`
("Unsettled law — …"), and a way forward → `innovation` / `opportunity` — only when the
question was asked through that lens on purpose or the holding itself uses upside language.
Sentences are split without breaking on `Art.`, `U.S.C.`, `C.F.R.`. `sync()` runs at the end
of every docket cycle. Table `steering_insights` (migration `20260921000000`), internal.

Where insights surface:
- **Coder prompts** — `prompt_assembler` layer `expert_insights`: at most 5 lines, 1,200
  characters, headed "internal, under attorney review — not legal advice", and only when the
  task text shares ≥ 2 salient terms with an insight. Relevance is decided by content, never
  by guessing which project is which industry.
- **Internal memos** — `db_memo._build_prompt` lists up to three data-vertical positions as
  context, never as evidence; the fingerprint-citation rule is unchanged.
- **Owner report** — innovation pathways first, then regulatory gaps by risk band.

**`runner/output_grader.py` — every output graded, every call named.** `grade()` is
deterministic: empty, refusal, malformed JSON when JSON was asked for, unfilled placeholder,
rubber stamp (the same structured verdict ≥ 5 times in a caller's last 20), repetition,
truncation, too short, boilerplate. `model_gateway._record_operation` writes `quality_score`
and `verdict` on every row, marks replays `cached:<verdict>`, and files an anonymous
`completion` under `completion:<calling module>`. Grading never blocks or alters a
completion.

## Operating it

```bash
python3 runner/docket_matrix.py report        # coverage, innovation share, high-priority share
python3 runner/docket_matrix.py pick 6        # what the panel would answer next
python3 runner/docket_matrix.py generate 6    # fill the six emptiest cells now
python3 runner/docket_matrix.py backfill      # persist lens/risk tags on legacy rows
python3 runner/steering_insights.py sync      # distil any new cards
python3 runner/steering_insights.py brief "add a payout hold to the courier withdrawal flow"
python3 runner/output_grader.py audit         # per-caller quality of local-model calls
python3 runner/output_grader.py posts         # grade what was posted to Supabase
```

Knobs: `ORCH_EXPERT_INSIGHTS` (`false` hides every surface), `ORCH_INSIGHT_MIN_OVERLAP` (2),
`ORCH_INSIGHT_BRIEF_LINES` (5), `ORCH_INSIGHT_BRIEF_CHARS` (1200), `ORCH_DOCKET_VALUE_RANK`,
`ORCH_DOCKET_MATRIX_TOPUP` (4; `0` stops generation), `ORCH_DOCKET_INNOVATION_SHARE` (0.4),
`ORCH_DOCKET_MAX_HIGH_SHARE` (0.3).

## Tests

`runner/tests/test_docket_matrix.py`, `test_steering_insights.py`, `test_output_grader.py`.
None touches a network or a database.
