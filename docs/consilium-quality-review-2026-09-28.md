# Tribunal quality review — 2026-09-28

_Sixteen days after Consilium v2 was scheduled. Every number below was read from the control
plane, the tournament transcripts, or an independent fetch of the cited sources on the day of
the review._

## 1. What the tribunal produced

| | Frontier era (Sep 12-21) | Local era (Sep 22-28) |
|---|---|---|
| Engine | Fable 5.1 / Opus 5, two-phase | local models only, "never escalate" |
| Cards minted | 33 | 52 |
| Citations per card (median) | 15, of which 12 verified | 4, of which 2.5 verified |
| Memo length (median) | 7,800 characters | 5,100 characters |
| Stated confidence (median) | 0.78 | 0.95 |
| Commission composite (median) | 0.70 | 0.29 |
| Accepted for steering | 27 | 0 |
| Rejected or sent back | 6 | 51 |

Other outputs: 4 regulatory opportunity briefs, 13 guidance ambiguity reviews, 0 papers.

## 2. Are the citations real?

Independent check: 140 citations marked verified were re-fetched and the quoted text searched for
on the live page.

| | Sampled | Quote found verbatim or near-verbatim | Quote absent | Source unreachable |
|---|---|---|---|---|
| Frontier cards | 90 | 72 (90% of fetchable) | 8 | 10 |
| Local cards | 50 | 45 (96% of fetchable) | 0 | 3 |

Grounding works. The local tier's rate is higher because its quotes are cut mechanically from the
page; its weakness is reasoning, not citation. The 8 absent frontier quotes cluster on
law.cornell.edu pages where the model paraphrased while marking the quote verbatim.

## 3. Quality against the uses that matter

| Use | Finding |
|---|---|
| Stating the law and what flips it | Strong on the frontier tier. Reviewers scored evidence 0.78-0.89 and utility 0.78-0.90. The cross-vendor attack adds real value: on the best card GPT-5.5 found a missed licence condition (SR Code 3.9.1) and the memo was rewritten around it. |
| Pathways and creative structures | Absent by design. 1 of 33 frontier cards presented alternatives. The output schema had nowhere to put a pathway. |
| Jurisdictional arbitrage | Absent. 0 of 33 frontier cards compared jurisdictions. |
| Regime weaknesses | Partial. The ambiguity miner works, but corpus text includes scraped site navigation, so the deterministic scanner's top findings on the sampled document were all false positives. Fable caught this and reviewed the real text. |
| Opportunities | Good. The opportunity scan is the strongest offensive component: dated, sourced, with deadlines and what to sell. |
| Novelty | Low. The novelty reviewer scored frontier cards 0.20-0.58: "settled and familiar to any practitioner". The questions ask for settled law. |
| Calibration | Inert. 17 of 17,813 staked positions resolved. Seven experts have any Brier record. |

## 4. Root causes

1. **Engine policy.** Local-only ran for a week and produced 52 cards of which 51 failed review,
   at a stated confidence of 0.95.
2. **Question quality.** The docket was written by small local models filling a grid. In a random
   sample of 30 pending questions, 27 had a false premise or a misattributed provision.
3. **No offensive structure.** The tournament defends an answer. Nothing generated options.
4. **One gate for two uses.** A low publication-exposure score withdrew cards from internal
   steering. Six well-grounded frontier cards were withdrawn for being too directive to publish.
5. **Silent write failures.** The heartbeat and theory-lab statistics had never been written
   (`controls.scope` is required). Refutations and resolutions were rejected by a check constraint
   on `expert_memory.kind` and swallowed.
6. **Host contention.** 1,366 launches were deferred in two weeks for memory pressure, headroom or
   load, including jobs that do all their reasoning on the subscription tier.
7. **Severity vocabulary.** Adversaries wrote "medium", "moderate", "high" and full sentences; only
   the literal words "fatal" and "material" triggered a revision.
8. **Orphaned worktree.** The worktree's git admin directory had been pruned, so nothing could be
   committed from the directory the scheduler runs from.

## 5. What changed on 2026-09-28

| Change | Where |
|---|---|
| High-priority questions are debated on the frontier tier; medium and low stay local | `consilium_v2.py` (`ORCH_CONSILIUM_FRONTIER_PRIORITIES`, default `high`) |
| Structuring tribunal: regime map, weak points, jurisdiction matrix, 4-7 ranked pathways, each attacked by a second model family, adjudicated, scored, with kill criteria | `pathway_lab.py`, tables `pathway_runs` and `verdict_pathways` |
| Citations in pathway runs are verified by our own fetch; the model's flag is discarded | `pathway_lab.verify_all` |
| Two-track gate: exposure blocks publication only; an exploratory posture keeps novel, grounded positions; the evidence floor is unchanged | `publication_commission.decide` |
| Stored reviews re-decided under the new gate, no model calls: 5 cards restored to steering, 7 moved from rejected to revise | `publication_commission.py regate --apply` |
| Docket triage: keep, rewrite or retire; calibrated priority; a lens per question; reversible ledger | `docket_triage.py` |
| Paper drafter accepts well-grounded steering cards with a modest new angle | `paper_drafter.py` |
| Heartbeat and statistics are written with the required scope | `consilium_controls.py` |
| Refutations stored as `correction`, resolutions as `outcome` | `theory_lab.py` |
| Severity normalised to fatal, material, marginal, none | `consilium_v2._sev` |
| A memo that calls a question unsettled has its confidence capped at 0.75 | `consilium_v2.run` |
| Frontier-capable jobs run on a constrained host with local inference switched off | `consilium_tick._light_admission` |
| Worktree git link rebuilt and locked against pruning | `.git/worktrees/consilium-v2` |

## 6. The line the structuring tribunal does not cross

A pathway changes the facts so that a rule is satisfied or does not apply: product mechanics, a
licensed partner, an entity or jurisdiction, an exemption whose conditions are met, a sequenced
entry, a no-action or comment request. It does not propose concealment, a misstatement to a
regulator, bank or partner, a sham without economic substance, or structuring to defeat a
threshold. The adversary is instructed to mark any pathway that drifts toward those as fatal.
Aggressive-but-arguable routes are allowed, labelled, and priced with durability and enforcement
probability.

## 7. Still open

- **Calibration** needs resolvable forecasts. Staking only 24-month predictions means Brier stays
  empty. Short-horizon, checkable claims should be staked alongside.
- **Corpus hygiene.** Navigation text in `corpus_clauses` should be stripped at ingest.
- **Host capacity.** Local-tier jobs (`expert_corps`, `corpus_forecaster`, `corpus_index`) still
  defer when the machine is busy. `expert_corps` last completed on Sep 12.
- **Corps bloat.** `expert_memory` holds 146,560 rows, 499 with a source URL.
- **Codex limits.** The cross-vendor adversary hit the ChatGPT plan's usage limit 13 times; Opus 5
  is the fallback, which is a second model but not a second vendor.
- **Frontier safeguards.** One wagering tournament was refused by the frontier model's content
  classifier and retried on the mid tier. Prompts framed as lawful structuring avoid this.

## 8. Follow-up, 2026-09-29: local tribunal v3 and never-idle

**Why the first local tier failed.** It asked a small model to do a large model's job in one
breath per round and to recall citations from memory. The commission rejected 51 of 52 of its
cards at a stated confidence of 0.95.

**What replaced it** (`runner/local_tribunal.py`). Narrow tasks a mid-size model does reliably,
and bytes wherever bytes can decide:

| Step | Who decides |
|---|---|
| Discovery | Official search APIs (eCFR, Federal Register, CourtListener leads), rule-resolved citations, playbook authorities, the corpus |
| Passages | Exact slices of pages the system fetched; breadcrumbs and page chrome excluded |
| Findings | The model picks quotes; each is re-checked as a substring, repaired from the passage or dropped. Strong passages the model skipped enter mechanically |
| Claims | Three seats answer claim by claim, each naming its findings |
| Verification | Each claim checked against only its own quotes: supported, narrowed, or struck |
| Memo | Written from verified claims; every legal sentence must carry a finding or it is tied to one (and checked) or struck |
| Citations | Built from the findings the memo used. A model never writes a citation |
| Citation audit | Authorities the memo names that are not in the record are listed and lower confidence |
| Confidence | Computed from claim coverage, issue coverage, sources, seat agreement, adversary severity. The model is never asked |
| Gate | Abstains, keeping the ledger, when evidence does not support a memo |

**Live result on the 9B model** (the only local model that fit): 12 of 12 legal sentences carried
a finding (was 9 of 20 on the first run), 10 findings, 8 citations each a verbatim slice of a
fetched page, computed confidence 0.55, a fatal adversary attack answered by revision. Remaining
errors were mechanical and are now caught: a pre-2011 citation name ("31 CFR 103"), generic source
labels, one breadcrumb quoted as evidence.

**Playbooks** (`runner/playbooks.py`) distil the frontier memos once per vertical into what to
check, which authorities decide it, common false premises and decision rules. The local tier reads
them at zero cost.

**Memo writer.** Research, extraction and verification stay local. The memo can be written by the
strongest local model or by Sonnet from the verified ledger; `local_benchmark.py` writes both from
the same evidence, scores both with the commission, and records the winner in `pen_policy.json`.
It runs weekly once a 20B+ local model fits.

**Never idle** (operator direction). Every call walks Claude -> GPT-5.5 -> the strongest local model
(`frontier.complete`), and jobs gate on `frontier.can_think`. Routine no-tool work goes to a
resident 20B+ local model first. Lower tiers have limited authority: expert scoring and playbooks
need a cloud tier; a local-tier commission review is provisional; a local-tier docket clerk may only
re-prioritise. A login failure is re-probed every five minutes.

**Host memory.** The Ollama app's default context was 262,144 tokens, so a 12B model took about
17 GB. It is now 32,768. Other workloads on this Mac still regularly leave under 5 GB free, which
keeps the 27B/35B rungs out of reach for much of the day.

## 9. The firm: associate -> senior associate -> counsel -> partner (2026-09-29)

**Why.** A frontier tournament cost about 72K input and 23K output tokens per question, and 60K of
that input was research the local tier can now do for free. Most docket questions do not need a
partner's judgement at all.

| Level | Model | Does | May finish |
|---|---|---|---|
| Associate | Fast local mid rung (Qwen3.5-35B-A3B; today whatever fits) | Research, evidence ledger, verified claims, draft, computed confidence | Low and medium, when earned |
| Senior associate | Next local rung up (Qwen3-Next-80B) | Reviews the associate's packet: agree, amend or redo; rules each issue settled, contested or open | Low and medium, when earned and every issue is settled |
| Counsel | Largest local rung (Qwen3.5-122B), else Sonnet, else GPT-5.5 | Reviews the senior's memo and rulings, writes from the ledger, decides whether a partner is needed | Any priority |
| Partner | Fable, GPT-5.5 when Claude is down | Rules only on contested issues from a brief; named gaps researched locally first, web tools only for what remains | Any priority |

**Earned trust.** Counsel spot-checks a fixed 25% of lower-level finals. Every review is recorded
as agree, amend or redo against the level that wrote the draft. Each level's local-final threshold
rises when the level above keeps amending it and falls when it keeps agreeing.

**Firm memory.** Settled issues become holdings with their verbatim authority, and counsel's
corrections are kept. The associate reads the nearest holdings and corrections on every new matter
and opens the holdings' authorities first. An issue that once needed a partner is then settled lower.

**Other levers.**
- **Precedent.** A docket question matching an answered one is retired with zero model calls.
- **Commission.** It rejects on the bytes when no cited quote is on its page. Associate-finished
  cards are reviewed at the associate's level and sampled by spot checks.
- **Packets.** The pathway tribunal and the paper drafter receive their authorities already opened,
  and get fewer research turns.
- **Capacity rule.** Associate work runs only on a local model or lean Claude calls. A GPT-5.5 call
  carries about 18K tokens of fixed overhead, so with neither available, medium and low matters wait
  and high ones go straight to one partner call.

**Status.** 197 tests pass. The first live matters run automatically once the teammate's benchmark
releases the machine's heavy lock and a 20B+ local model fits; results go to
`<home>/consilium/escalation_ledger.jsonl` (`python3 runner/escalation.py report`).

## 10. Demand first: the law app's gaps become the docket (2026-09-29)

**Why.** Triage found 93% of the synthetic docket needed rewriting or retiring. Meanwhile the law app
held 5,380 open `advisory_inquiry_gaps`: questions its own advisory engine could not answer, each
recording how many propositions it blocks. Answering a gap unblocks product.

**Intake** (`runner/gap_intake.py`). Free rules route each gap to its cheapest resolver:

| Class | Open gaps | Resolver |
|---|---|---|
| provision_reading | 3,562 | Clerk lane: docketed, capped at medium priority so it stays with the associates |
| interpretive | 774 | The full firm; carries most of the value (top items: chance-vs-skill tests, tribal IGRA classification) |
| unsorted | 795 | A local model sorts them (`--sort`); never the cloud (operator choice) |
| operator_fact | 157 | The client answers; not docketed |
| retrieval | 44 | A corpus acquisition task; not docketed |
| off_topic | 28 | Skipped |
| regulator_only | 20 | Outreach; not docketed |

Value is propositions blocked (sentinels 99/999 capped at 10) plus priority, weighted 3x for the
product engine's own gaps. The first 200 imported carry 17,308 of about 26,000 total value. While any
gap question is pending, `legal_docket` answers gaps first by value and the synthetic matrix top-up
and the forecaster's anticipation are paused.

**Write-back** (`runner/gap_writeback.py`). An accepted card on a gap question becomes an
`advisory_inquiry_answers` row linked to the gap: `internal_only`, informal, source "Apparently Law
research (Consilium)", no invented responder. Operator policy: below medium risk, attorney review is
optional and the gap is marked `answered`; at medium or high it stays `open`. A provisional
(local-tier) acceptance, composite under 0.6, fewer than 3 fetched citations, or an answer found by
precedent is at least medium. Gaps retired as duplicates of an answered card get that card's answer
at zero model cost.

**Commission ladder.** Mechanical citation check, then the evidence reviewer, then one panel call
scoring rigor, novelty, utility and exposure together. Only a card whose panel composite comes within
0.06 of the publication bar gets the separate reviewers, including the cross-vendor exposure check.
Steering and revise decisions come from the panel: about four reviewer calls become one for most
cards. A failed panel falls back to the separate reviewers (`PUBCOM_PANEL=false` turns it off).

## 11. Question families: one chart instead of one tournament per jurisdiction (2026-09-29)

**Why.** Two gap families, "which chance/skill test does <state> apply" (47) and "how would <tribe>
classify a game under IGRA" (35), were 81 of 4,336 docketable gaps and 78% of their value; each answer
unblocks about 57 propositions. As separate matters they would re-research the same general law 81
times and could disagree with each other.

**The pass** (`runner/family_matrix.py`, run by `legal_docket` before the one-at-a-time route):

| Step | Who decides |
|---|---|
| Family | Gap questions identical except for the place or party they name |
| Framework | Researched once per family and kept: IGRA and NIGC definitions; opinions that set the competing chance/skill tests side by side |
| Cells | Free: the jurisdiction's own courts (CourtListener, court-filtered, opinion PDFs opened), its tribal-state compacts (BIA index, 1,201 documents), the corpus |
| Passages | Windows centred on the question's own vocabulary (the options it lists); at least two subject words as whole words |
| Chart | One call per 4 cells: choice, short answer citing passage ids, status, verbatim quotes, and whether the sources concern the named entity |
| Verify | Every quote re-found in its passage. A cell must rest on its own sources; framework passages alone cannot decide a jurisdiction |
| Mint | Each settled or contested cell becomes that member's card, with the family comparison. Open cells retry, then go to the firm |

**Live validation (sandboxed, nothing minted).** Illinois (*Dew-Becker v. Wu*, 2020) and Iowa (*Banilla
Games*, 2018): predominant/dominant factor, each from its own supreme court. Laguna Pueblo, Oneida
Indian Nation and Saginaw Chippewa: Class III compacts covering electronic devices, internet play not
addressed in the passages opened. One chart call per four cells, about 22K tokens in on GPT-5.5.

**Caught before live use.** A prefix match mapped every "Class III" answer to "Class II"; the New York
Oneida Indian Nation matched the Oneida Nation of Wisconsin's compact; stemmed search matched "any
chance of finding employment"; a search outage would have been recorded as "no law exists". Each has a
test.

**Shared improvements.** `local_research.fetch` now reads PDFs (pdftotext, pypdf fallback), which every
tribunal benefits from. `authority_search.caselaw_opinions` searches one jurisdiction's courts and
returns each opinion's PDF; a failed search returns None, never an empty "no results".

**Tribal questions now name the games (later on 2026-09-29).** The law app's tribal questions come
from Smarter's membership generator. They used to ask how a tribe would classify "a game of this
kind" with no game described. Each now lists the 15 catalogued game types with their defining
features and asks for IGRA Class I, II, III or outside IGRA for each (Smarter migrations
20261019000300 and 20261019000400; the letter redraft is in kalepasch1/smarter#995). Consilium
refreshes pending docket rows when a gap's wording changes, and the family chart classifies each
listed game only from that tribe's own sources.

**Scheduler starvation fixed.** From about 14:00 every tick deferred: EXO reported 0.18 GiB available
while macOS could reclaim 9.8 GiB at warn pressure. Cloud-only jobs are now admitted on the kernel's
figure, and critical pressure still defers. Separately, manual runs of `gap_intake.py` had written
the gap map to `~/.claude-orchestrator` because the module read its home before loading
`runner/.env`. The tick uses `.runtime`, so the map was moved there.
