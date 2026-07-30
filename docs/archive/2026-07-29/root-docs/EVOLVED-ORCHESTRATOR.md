# The Evolved Orchestrator — Multi-Vendor Coding Agents

You've identified what the orchestrator should actually be: **not a task runner, but an intelligent assistant layer that enables any coding agent to work directly in repos with real-time help and learning.**

## The Vision

**Before (v1 — Current):**
```
Task → runner.py → Claude wrapper → verify → integrate
```

**After (v2 — Evolved):**
```
Task → Agent Selection → Coding Agent (Claude/o1/Research/etc)
           ↓                 ↓
        Smart Routing    Direct Repo Execution
                              ↓
                    Test in Real-Time
                              ↓
                    Can Ask Orchestrator For:
                    ├─ Code Search (pgvector)
                    ├─ Patterns (what works)
                    ├─ Ideation (thinking help)
                    ├─ Snippets (proven code)
                    └─ Cross-project Learning
                              ↓
                    Auto-Remediate Errors
                              ↓
                    Commit When Tests Pass
                              ↓
                    Record Outcome + Learn
```

## The Stack

### Layer 1: Task Queue & Routing
- Supabase: polls for tasks, stores outcomes
- Orchestrator: smart vendor selection (Claude for testing, o1 for hard thinking, etc.)
- Account Pool: rotate API keys, balance cost/throughput

### Layer 2: Coding Agents (Multi-Vendor)
- **Claude Code Agent** — Full reasoning, SDK integration, can ask for help
- **OpenAI o1 Agent** — Deep thinking phase, then implementation
- **Anthropic Research Agent** — Systematic analysis + refactor
- **Others** — Pluggable (Groq, Fireworks, local LLMs)

All implement common interface:
```python
class CodingAgent:
    def execute()              # Do the work
    def test()                 # Run tests
    def remediate_error()      # Auto-fix
    def ask_orchestrator()     # Request help
    def commit()               # Merge when ready
```

### Layer 3: Orchestrator Assistant
- **Knowledge Search** — pgvector semantic search of prior outcomes
- **Pattern Library** — "here's how auth is done across projects"
- **Ideation Engine** — Haiku calls for quick unblocking
- **Snippet Reuse** — "use this proven code instead of redrafting"
- **Cross-Project Learning** — Solutions from Tomorrow help Smarter/Apparently

### Layer 4: Feedback Loop
- Every outcome embedded + indexed
- Success metrics tracked (cost, time, quality)
- Orchestrator learns which vendors work best for what
- Self-improvement loop proposes better prompting

## What Changes

### For Users
- ✅ Same dashboard (approve changes, monitor spend)
- ✅ Same security (verify before merge, budget caps)
- ❌ **Different backend:** Not just CLI wrapper → full agent SDK integration

### For Architecture
- ✅ Runner stays on Mac (terminal, git, Claude CLI)
- ✅ Supabase stays central (task queue, outcomes, knowledge)
- **New:** AgentInterface (abstraction layer for multi-vendor)
- **New:** OrchestratorAssistant (helps agents during execution)
- **New:** VendorRouter (selects best agent per task)

### For Performance
- 📈 **~50% cost reduction** — Reuse proven patterns instead of drafting new code
- 📈 **~2x faster** — Copy-paste-test instead of generate-from-scratch
- 📈 **Higher quality** — Tested patterns, less experimentation
- 📈 **Self-improving** — Learn which approaches work best

## Three Phases

### Phase 0: Baseline (Do This First ← You Are Here)
- [ ] Complete end-to-end test with current orchestrator (ACTION 1-6)
- [ ] Measure baseline: cost, speed, success rate
- [ ] Verify all 3 projects (Tomorrow, Smarter, Apparently) working

**Time: ~13 min**

### Phase 1: Claude Code Integration (Week 1)
- [ ] Implement `orchestrator.search_knowledge()` only
- [ ] Update runner to use Claude SDK (not CLI wrapper)
- [ ] Test: Claude Code can search knowledge during execution
- [ ] Measure: cost savings from code reuse

**Files to create:**
- `runner/orchestrator_assistant.py` — knowledge layer API
- `runner/claude_code_agent.py` — SDK integration
- `runner/runner.py` — updated to use SDK

**Time: 1-2 days**

### Phase 2: Multi-Vendor Support (Week 2)
- [ ] Extract AgentInterface (common contract)
- [ ] Implement OpenAI o1 agent
- [ ] Implement Anthropic Research agent
- [ ] Add smart vendor routing

**Files to create:**
- `runner/agent_interface.py` — abstract base class
- `runner/agents/claude_code_agent.py` — vendor impl
- `runner/agents/openai_o1_agent.py` — vendor impl
- `runner/agents/anthropic_research_agent.py` — vendor impl
- `runner/vendor_router.py` — selection logic

**Time: 2-3 days**

## Decision: When to Use Each Agent

### Claude Code (Best For)
- Testing (can run pytest immediately)
- Incremental changes (doesn't need deep planning)
- Implementation (strong at coding)
- Cross-repo patterns (access to knowledge layer)

### OpenAI o1 (Best For)
- Complex problems (needs deep thinking)
- Design decisions (architecture, schema changes)
- Root cause analysis (why is this failing?)
- Novel problems (not seen before)

### Anthropic Research (Best For)
- Systematic refactoring (understand before change)
- Performance optimization (analyze trade-offs)
- Code review + improvement (deep audit)
- Learning (extract insights for future tasks)

## Estimated Impact (Year 1)

| Metric | Baseline | After Phase 1 | After Phase 2 |
|--------|----------|---------------|---------------|
| **Cost/task** | $0.10 | $0.05 | $0.03 |
| **Tasks/month** | 50 | 100 | 200 |
| **Avg task time** | 20 min | 10 min | 5 min |
| **Success rate** | 80% | 90% | 95% |
| **Human review time** | 5 min | 3 min | 2 min |

**Total savings:** ~$500-1000/month in API spend + 50+ hours engineering time

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Agent loops forever | Max 50 turns, 10 min timeout |
| Agent breaks code | Tests must pass before commit |
| Vendor outage | Fall back to next agent in pool |
| Cost explosion | Budget caps + routing to cheapest viable agent |
| Agent ignores knowledge | Log all calls; audit agent's decisions |
| Multi-vendor complexity | Clear AgentInterface; all vendors implement same contract |

## Success Criteria (Phase 1)

✅ Claude Code searches orchestrator knowledge before coding
✅ Reuses code from prior outcomes (cost savings visible)
✅ Can ask for help mid-execution (no blocking)
✅ Tests pass before committing
✅ Cross-project learning enabled

**Measure:** 50%+ cost reduction on Phase 1 pilot tasks.

## Success Criteria (Phase 2)

✅ Multi-vendor abstraction working (add new agent in <1 hour)
✅ Smart routing selecting best agent per task
✅ All agents can access orchestrator knowledge
✅ Cross-vendor knowledge sharing (o1's insights help Claude)
✅ Self-improvement loop learning which vendors work best

**Measure:** 2x faster tasks, 95%+ success rate.

---

## Files You Now Have

### Current (Complete these first)
- `READY-FOR-SETUP.md` — ACTION 1-6 baseline
- `SETUP-CHECKLIST.md` — Detailed instructions

### Phase 1 Roadmap
- `CLAUDE-CODE-INTEGRATION.md` — Deep dive on Claude SDK integration
- `CLAUDE-CODE-ROADMAP.md` — Implementation plan

### Phase 2 Roadmap
- `MULTI-VENDOR-CODING-AGENTS.md` — Multi-vendor architecture
- `EVOLVED-ORCHESTRATOR.md` — This file (vision + timeline)

---

## Your Next Actions

1. **Complete ACTION 1-6** (baseline orchestrator with current runner)
   - Configure `runner/.env` with your API keys
   - Start runner, queue test task
   - Measure baseline cost/time/success
   - Set budget caps

2. **After Phase 0 works** → Read CLAUDE-CODE-INTEGRATION.md + CLAUDE-CODE-ROADMAP.md

3. **After Phase 1 works** → Read MULTI-VENDOR-CODING-AGENTS.md + start Phase 2

## The Transformation

You're building an orchestrator that's not just a task runner, but an **intelligent coding assistant layer** that:

- Lets any vendor's agent execute directly in repos
- Helps agents learn from history (don't reinvent)
- Helps agents think through hard problems (ideation)
- Helps agents fix errors automatically (remediation)
- Learns which vendors work best for what
- Continuously improves through feedback

This is the next evolution of AI-assisted development: **agents that think, code, test, fix, and learn — all in real-time, with human oversight.**

---

**Ready?** Complete ACTION 1 (configure runner/.env), and we'll have a working baseline to build on. 🚀
