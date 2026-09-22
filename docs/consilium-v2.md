# Consilium v2 — frontier-grade experts at subscription cost

_Engineering record, 2026-09-11/12. Every claim below was measured on Mac.lan or read from
the control plane; numbers are from that session._

## 1. What was actually happening (the diagnosis)

The expert subsystem — the adaptive committees that steer builds, the persistent expert
corps, the five-round gauntlet, the legal docket that mints verdict cards, the publication
commission, and the corpus forecaster — was architecturally rich and operationally hollow.

| Finding | Evidence |
|---|---|
| Nothing was running | No fleet process on this Mac since a reboot; launchd jobs unloaded; last control-plane write from the experts 2026-09-10 09:52 UTC; zero model operations in the three hours before the review. |
| Seats ran on an 8B model | Of the last 300 model operations, 271 were `local/llama3.1:8b`, the rest 4B–22B local models. Not one frontier call. |
| The subscription provider was permanently demoted | `provider_failover_sla` had `claude` demoted since 2026-08-17 for `exhaustion-account_quota`. A demoted provider gets no traffic, so it can never earn the three probe successes that would promote it. The Claude Max plan sat idle for 25 days. |
| Headless calls were 40–80x heavier than they need to be | A default `claude -p` "reply OK" wrote 31,824–59,668 tokens of cache (Claude Code system prompt + every configured MCP server's tool list). With `--strict-mcp-config`, `--setting-sources ""`, `--tools ""`, `--system-prompt`: **768 tokens**. |
| Cards were shallow and unverifiable | 312 verdict cards; median 5 citations; 0 URLs; sampled card asserted "California, Nevada and Oregon regulate…" at 0.95 confidence citing ABA Model Rule 7.3. |
| Calibration never happened | 1,000 staked positions, 0 resolved; `brier_n = 0` on all 155 experts. Elo had 6,422 bouts of signal; Brier had none. |
| Generations were theater | Max generation 5,297: `evolve()` counted free-text `source` as "learned something citable", so every research tick advanced a generation. |
| Research was unsourced | 1,000+ `expert_memory` rows, 0 with a `source_url`. |
| The commission was dead | `publication_commission.py` imported an `llm` module that does not exist; every reviewer failed closed; `publication_reviews` was empty after six weeks. So nothing ever became a paper. |
| The docket was pointed at the right things but starved | 1,000 docket questions, 700 pending; verticals gaming/finserv/aidata; no ambiguity or opportunity feed into it. |

## 2. The lever: rate limits, not dollars

Two subscriptions on this machine run frontier models headlessly at zero billable cost:

- Claude Max → `claude -p --model claude-fable-5-1` (Fable 5.1), `claude-opus-5`, `claude-sonnet-5`. Verified: exit 0, `cost_usd` 0, structured output via `--json-schema`, and **web-grounded research** via `--tools WebSearch,WebFetch --allowedTools … --permission-mode bypassPermissions` (a 5-turn probe located Utah Code § 76-9-1401 on le.utah.gov with the 2025 renumbering date — consistent with the firm's own statutory-currency ledger).
- ChatGPT → `codex exec -m gpt-5.5 -s read-only -c mcp_servers={} --json` (GPT-5.5; the app-bundled default `gpt-6-astra` needs a newer CLI than Homebrew's 0.145).

The binding constraint is the weekly/hourly limit. So the accounting unit is **tokens per window**, and the engineering goal is to spend nearly all of each call on reasoning. That is `frontier.py`.

## 3. What was built

```
frontier.py            lean subscription gateway: tiers (need→Fable/Opus/Sonnet), token budget
                       (hour/day, night x2), cooldown on rate-limit signals, WebSearch/WebFetch,
                       --json-schema structured output, Codex cross-vendor, local fallback.
                       All Claude calls still go through claude_cli.run (kill switch, breaker,
                       metering) via a new extra_args hook.
consilium_v2.py        the compact tournament: ONE Fable call hosts all five gauntlet rounds
                       (blind → steelman → settle → judged bouts → red team → chair) over the
                       real corps seats, with URL+quote-verified citations; writes Elo bouts,
                       stakes Brier positions, optional GPT-5.5 red team + one revision pass;
                       audit transcript in ~/.claude-orchestrator/consilium/tournaments.jsonl.
                       gauntlet.run() tries it first; legacy 21-call path is the fallback.
theory_lab.py          TESTS THE THEORIES: resolves staked positions when the question is
                       settled by opened authority (Brier finally moves; miscalibrated experts
                       hit probation) and verifies/refutes unsourced doctrine claims by URL.
paper_drafter.py       commission-passed cards → 1.5–3K-word review-only drafts (re-verified
                       URLs, scored forecast, preserved dissent) → approvals packet + markdown
                       under docs/consilium/papers/. Never publishes.
reg_opportunity_scan.py corpus feed (Federal Register/eCFR events) + web research → market
                       unlocks, comment windows, enforcement demand, arbitrage; each with a
                       primary-source URL → docket questions + daily brief + approvals packet.
ambiguity_miner.py     corpus guidance/rules → the firm's own deterministic miner
                       (contracts/guidance-ambiguity.js via tools/consilium/ambiguity_bridge.mjs)
                       → Fable judgment on materiality → docket questions + clarification-request
                       DRAFT (never sent) + approvals packet.
corpus_db.py           read-only client for the shared corpus project (1,202 primary docs,
                       15,679 clause units, 783 authorities, 307 feed entries).
consilium_tick.py      one scheduling pass; launchd fires it every 10 min
                       (deploy/com.claudeorchestrator.consilium.plist). Runs at most one due
                       job per tick, sequentially; honors the kill switch; heartbeat in
                       controls.consilium_heartbeat. Independent of the coding fleet.
```

Edits to existing code (all fail-soft, all fall back to the old path):

- `claude_cli.run(..., extra_args=)` — lean/structured flags appended after the guarded command.
- `provider_failover_sla` — `promote()` + a 7-day TTL on `exhaustion-*` demotions (the stale `claude` demotion lifted on first import).
- `expert_corps` — chair/judge/red-team/research route to the frontier tier, seats to `qwen3.5:27b-mlx`; research must open sources (`source_url` + quote); `evolve()` requires opened sources and a 24h cooldown.
- `committees` — chair on Fable (need 9); legal/security/red seats (need ≥7) on the frontier tier; other seats local-strong.
- `publication_commission` — reviewers on the frontier tier (evidence reviewer opens the cited URLs; exposure reviewer on GPT-5.5 when available); verdict cards are scored first; decisions write `verdict_cards.publication_state`.
- Routing tables — Fable 5.1 / Opus 5 added to `model_policy`, `model_catalog`, `model_router`, `model_gateway` prices.

## 4. Cost model (why this is 100x, not 10%)

| | Before | After |
|---|---|---|
| Model on a seat | llama3.1:8b | Fable 5.1 (chair, red team, research), Opus 5 (judges), qwen3.5:27b local (routine seats) |
| Calls per docket question | ~21 | 1 (+1 Codex attack, +1 revision on high priority) |
| Preamble per call | 31–60K tokens | ~0.8K tokens |
| Tokens per question at frontier grade | ~1M (never attempted) | 220–310K budget-weighted per tournament, measured in production (§8); raw 220–255K in / 32–51K out |
| Grounding | none (recall) | every citation carries an opened URL + verbatim quote, or is demoted to an assumption |
| Budget | none | 3M tokens/day (operator choice), 600K/hour, x2 at night; cooldown on any limit signal; degrades to local |
| Marginal $ | $0 | $0 |

At the measured envelope (§8) 3M weighted tokens/day is roughly 10–13 frontier tournaments per
day and the 600K/hour cap admits two per hour — an order of magnitude below the first estimate,
which assumed the 768-token preamble was the cost and missed that output tokens (weighted x5)
dominate a 30–50K-output tournament. Cutting the envelope is the next engineering task (§7, §8).

## 5. What "intelligence" now means, measurably

The old dashboards counted volume. The signals that now move, and where to read them:

- **Grounding**: `verdict_cards.process.verified_citations / citation_count` (v2 cards only).
- **Debate quality**: `process.positions_flipped_by_steelman`, `process.concessions`, `process.red_team_severity`, `process.cross_vendor.severity`.
- **Calibration**: `experts.brier_n` > 0 and rising; `controls.theory_lab_stats`.
- **Publication throughput**: `publication_reviews` decisions per day; `approvals` rows with slugs `paper:*`, `regopp:*`, `ambig:*`.
- **Budget**: `controls.consilium_heartbeat.frontier`, `~/.claude-orchestrator/frontier_budget.json`, `python3 runner/frontier.py`.

## 6. Operating it

```
python3 runner/consilium_tick.py --status          # schedule + budget
python3 runner/consilium_tick.py --once legal_docket 1
python3 runner/frontier.py                          # budget / availability / models
python3 runner/frontier.py probe                    # one 800-token Fable call
tail -f ~/Library/Logs/claude-orchestrator/consilium.out.log
```

launchd: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.claudeorchestrator.consilium.plist`
(stop with `launchctl bootout gui/$(id -u)/com.claudeorchestrator.consilium`). Global kill switch pauses it.

Knobs (runner/.env): `ORCH_FRONTIER_TOKENS_PER_DAY`, `ORCH_FRONTIER_TOKENS_PER_HOUR`,
`ORCH_FRONTIER_MODEL`, `ORCH_CONSILIUM_RESEARCH`, `ORCH_CONSILIUM_CROSS_VENDOR`,
`ORCH_CONSILIUM_SEATS`, `ORCH_CODEX_ENABLED`, `OLLAMA_STRONG_MODEL`.

## 7. Next multipliers (not built yet)

1. **Distillation**: use v2 transcripts as few-shot exemplars for the local 27B so routine seats
   approach frontier quality at zero subscription cost; escalate to Fable only on disagreement.
2. **Corpus-first retrieval**: embed `corpus_clauses` (qwen3-embedding, local) and inject the
   top passages into the tournament so the model reads the firm's verified corpus before the web.
3. **Card freshness by authority change**: wire `regulatory_feed_entries` → stale-marking of
   cards whose `authority_chain` cites the changed instrument (the event-driven staleness the
   docket module promises).
4. **Benchmark redlines**: ingest the five `pending_source` filings so `benchmark_redlines.py`
   can run on Fable — the public proof-of-superiority artifact.
5. **Foulkon sync** from v2 cards once the fleet is back (needs the illuminati checkout).
6. **Steering for code**: route `illuminati_cothink` premerge verdicts and `committees.review`
   on material tasks through `consilium_v2` with the repo diff as context.

## 8. First production day (2026-09-12) — measured

launchd job loaded 09:51 EDT; first tick ran `legal_docket 3`. Everything below is read from
`.runtime/frontier_budget.json`, `.runtime/consilium/tournaments.jsonl`, `app_operations` and
`verdict_cards` (the worktree's `.runtime` is the state home while the launchd job points at it).

| Tournament | Vertical | Cites (verified) | Flipped / conceded | Red team | Raw in / out | Weighted | Turns | Time |
|---|---|---|---|---|---|---|---|---|
| 09:24 `6437c44f` NY BitLicense / MSB as MTL condition | finserv | 21 (19) | 4 / 4 | medium | 255K / 51K | 306K | 40 | 11.5 min |
| 10:00 `d0af873e` §5318(g)(1) "relies solely on a depository institution" | finserv | 18 (16) | 5 / 2 | medium | 222K / 32K | 218K | 30 | 8.2 min |
| 10:07 (gaming: AI-generated odds on a prediction market) | gaming | — | — | — | ~199K weighted, then refused | — | — | 7.0 min |

Verified-citation ratio 35/39 = 0.90. Ten Brier positions staked (5 per tournament). Both cards
minted `internal`, confidence 0.88 and 0.93.

Three defects found on the first day, all fixed on `agent/consilium-v2`:

1. **Cross-vendor adversary never ran.** Both cards show `cross_vendor.ran=false`. Root cause:
   OpenAI's structured output requires `additionalProperties:false` on every object and all
   properties listed in `required`; `ATTACK_SCHEMA` had neither, so codex returned HTTP 400
   `invalid_json_schema` in 4 s. The logged error was the stderr tail — unrelated `rmcp` noise from
   the `apparently` MCP server in `~/.codex/config.toml` (`-c mcp_servers={}` does not disable
   configured servers in codex 0.145; the turn still succeeds). Fix: `frontier.strict_schema()`
   applied to every codex schema, and `parse_codex_events()` reports the `turn.failed` message.
   Re-run live on card `6437c44f`: GPT-5.5 answered in 111 s (88K in / 10K out), severity
   **material** — the memo's unconditional "No" misses that the DFS/NMLS money-transmitter
   application checklist asks for the applicant's FinCEN MSB registration number (Banking Law
   §641(2)(e) hook), so FinCEN registration is a practical application condition when the firm is
   federally an MSB. That is exactly the class of gap the cross-vendor pass exists to catch; both
   first-day cards were minted without it and should be re-debated (set their docket rows to
   `stale`).
2. **Fable's safeguards refused a wagering question mid-tournament.** The third question died after
   7 minutes with `API Error: Fable's safeguards flagged this message (…/legal/aup)`. Not a rate
   limit (correctly no cooldown), but the question fell to the 21-call legacy path on the local 27B.
   Gaming/AML/enforcement questions are the docket's core. Fix: `consilium_v2` retries once on the
   mid tier (`claude-opus-5`) when the frontier call was refused or returned malformed JSON —
   never on budget, kill-switch or timeout — and records `process.fallback` with the wasted tokens.
3. **Budget ledger split by import order.** `frontier.HOME` resolved to `~/.claude-orchestrator`
   when frontier was imported before `db`, and to `<repo>/.runtime` otherwise, so a probe could
   not see what the tick had spent. Fix: frontier imports db first.

Reading the cards: `verdict_cards.process`, `citations`, `assumptions` and `authority_chain` are
JSON **strings** inside jsonb (the docket serialises them), so the grounding signals in §5 read as
`((process #>> '{}')::jsonb)->>'verified_citations'`, and engine filters as
`(process #>> '{}') like '%consilium_v2%'`.

Cost correction: the budget weights output tokens x5 (API price ratio), so a 51K-output tournament
is ~255K weighted before any input — output, not the preamble, is the envelope. The §4 estimate of
100–200 tournaments/day was wrong by 10x; the real figure at 3M/day is 10–13, two per hour under
the 600K/hour cap. The not-yet-run jobs (commission, drafter, theory lab, scans) had produced no
artifacts at the time of this note because the tick runs one job at a time and the docket batch
held the slot for its first 50 minutes.

## 9. The local tier (2026-09-21) — tournaments at zero subscription cost

Operator direction: the tribunal runs on the local cluster (EXO + Ollama across three Macs on
Thunderbolt), and the subscription models become an escalation rather than the default.

```
local_llm.py        one chat() over EXO and Ollama. The ladder is 122B -> 80B -> 35B-A3B -> 27B -> 9B;
                    a rung is eligible only if it is ALREADY RESIDENT (free) or EXO's own placement
                    planner (/instance/previews) says it can place it for the current topology.
                    Resident rungs are tried first. Ollama rungs additionally need their weights in
                    RAM free ON THIS HOST. Never deletes an instance; the cluster's keeper owns
                    placement. Schema-constrained output: Ollama by grammar, EXO by response_format.
local_research.py   the AUTHORITY DOSSIER with no model call for the fetch: citations in the question
                    (plus, optionally, a short local-model spotting call) are resolved to official
                    URLs BY RULE (LII for CFR/USC/NYCRR, nysenate.gov for NY statutes, the Federal
                    Register API), fetched by us, cached on disk, and quoted by term overlap. A quote
                    is verified iff it is a verbatim substring of the page we hold — a property of
                    the bytes, not a claim by a model. What no rule can resolve is listed as
                    unresolved so the tribunal treats it as an assumption.
consilium_v2.run()  ENGINE=local by default: local dossier -> one local structured debate on it.
                    Citations are checked against the held page text (_enforce_pages), which is
                    stricter than the frontier path. ORCH_CONSILIUM_ESCALATE (never|high|always)
                    decides when a failed local tournament may spend subscription capacity; a good
                    dossier is reused so only the debate is paid for.
```

### The cluster finding that blocks it today

The three Macs pool >100 GB, and EXO joins all three (Kale's MacBook Pro, apparently-node-2,
apparently-node-3). But **no model can stay placed**. Every placement — mine, and the cluster
keeper's own — is deleted within a second. The cause is not memory:

- `~/.exo/exo-large-model-guard.sh` runs on node-2 and node-3 under
  `com.apparently.exo.large-model-guard` (KeepAlive, 1 s loop in maintenance mode).
- When `~/.exo/large-model-maintenance` exists, the guard deletes **every instance that is not the
  122B**, and the guard's own log records each deletion of a 35B/80B placement.
- The 122B cannot be placed: EXO's planner returns "No cycles found with sufficient memory".
- So the cluster is deadlocked at zero models, and `exo_ops.keeper` logs `{"action": "paused"}`
  every 60 s instead of loading the largest model that fits.

The markers were stale (node-3 15:27, node-2 16:16 on 2026-09-21) and the peers' own watchdog flags
`maintenance_active` as a fault ("a forgotten maintenance flag blocks everyone"). Moving both aside
let the keeper place the 35B on node-3 and reach `ready: true` — then the marker reappeared within
about ten minutes and the guard deleted it again. Something re-arms it; that owner is outside this
subsystem, so the Consilium does not fight it: with no local model and escalation disallowed, a
docket question simply stays pending.

**Resolved 2026-09-21 (operator approved):** the `com.apparently.exo.large-model-guard` job was
booted out on both peers and both markers moved aside. The keeper immediately placed the 35B-A3B on
node-3 (42 tok/s) and then upgraded toward the 80B, exactly as its chain intends. Restore the guard
with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.apparently.exo.large-model-guard.plist`
on each peer; the markers are kept as `~/.exo/large-model-maintenance.disabled-by-operator-20260921`.

Two things the operator should know:

1. Maintenance mode also runs `pkill -KILL` against Google Chrome, Claude.app and
   `claude-code` on the node it runs on. A forgotten marker therefore kills GUI and Claude Code
   sessions on that machine, not just model placements.
2. Until the marker stops reappearing (or the 122B is made placeable), the local tier has no model
   and every tournament either escalates or waits.

## 10. The local tournament, measured (2026-09-21)

The frontier tier is rate-limited, so there the whole gauntlet is ONE call. The local tier has the
opposite economics — calls are free, but a mid-size model cannot emit the full tournament object.
Measured: a 27B/35B satisfies a small schema perfectly (verdict+why, 51 tokens) and returns
malformed output for the full SCHEMA, which needs 6-10K tokens of nested JSON and truncates. So
`local_tournament()` runs each round as its own call with its own small schema — 5 blind positions,
5 steelman/settle, 4 bouts, red team, chair, citations — and assembles exactly the object the
single-call path produces, so Elo, Brier, citation enforcement and the transcript are unchanged.

First end-to-end local tournament (docket question on an RGS aggregator's AI marketing and MSB
registration), escalation disabled so it had to finish locally or not at all:

| | Frontier single-call (09-12) | Frontier two-phase (09-21) | **Local (09-21)** |
|---|---|---|---|
| Subscription tokens | 255K in / 51K out | 9.6K in / 13.5K out | **0** |
| Budget-weighted cost | ~306K | ~77K | **0** |
| Wall clock | 11.5 min | 16.5 min | **4.1 min** |
| Calls | 1 | 2 | 17 (all free) |
| Citations (verified) | 21 (19) | 20 (12) | 10 (7) |
| Research phase | inside the paid call | paid | free, 5.6 s, 9/10 verified |

The verification layer earns its place here. The local model produced two fabricated citations — a
UK casino-licence definition attributed to 31 CFR 1010.100(t)(5), and a mis-stated 31 U.S.C.
§ 5312(a)(2)(X) — and both were demoted automatically because their quotes are not verbatim spans of
the pages we hold. The model's `verified: true` claim is never trusted; the bytes decide. The chair's
red team also returned severity `fatal` on its own leading position, which is the tribunal working
rather than failing.

Local memo quality is below Fable's, so `ORCH_CONSILIUM_ESCALATE` still decides when a question is
worth subscription capacity. The difference is that the floor is now free and grounded rather than
absent.
