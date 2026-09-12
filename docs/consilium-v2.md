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
| Tokens per question at frontier grade | ~1M (never attempted) | 15–40K measured envelope |
| Grounding | none (recall) | every citation carries an opened URL + verbatim quote, or is demoted to an assumption |
| Budget | none | 3M tokens/day (operator choice), 600K/hour, x2 at night; cooldown on any limit signal; degrades to local |
| Marginal $ | $0 | $0 |

At 3M tokens/day the Consilium runs on the order of 100–200 frontier tournaments per day. The
700-question backlog clears in under a week; after that the budget goes to re-debating stale
cards, opportunity scans, ambiguity reviews and calibration.

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
