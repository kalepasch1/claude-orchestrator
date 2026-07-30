# Claude Code Integration — Quick Start Roadmap

You've identified a critical gap: the orchestrator should use Claude Code as a **direct agent** with access to the knowledge layer, not as an isolated wrapper.

## The Gap (What We're Fixing)

**Current:** Task → runner.py wrapper → CLAUDE_BIN=claude (isolated) → verify → integrate
- ❌ Claude Code can't access orchestrator's knowledge
- ❌ Can't reuse snippets from prior outcomes
- ❌ Can't ask for real-time help if stuck
- ❌ Redundant code generation across tasks

**Desired:** Task → Claude Code Agent (with orchestrator context) → tests & commits
- ✅ Searches orchestrator knowledge before coding
- ✅ Reuses proven code from prior outcomes
- ✅ Can ask for ideation/unblocking mid-execution
- ✅ Learns from every successful task

## Quick Implementation (Estimate: 2-3 days)

### Step 0: Verify Current Setup Works (**Do this first**)
Complete the 13-min end-to-end test with current runner:
1. Configure `runner/.env` (ACTION 1 you're on now)
2. Start runner (ACTION 2)
3. Queue test task (ACTION 4)
4. Monitor execution (ACTION 5)

**Why:** Baseline the current system before we optimize.

### Step 1: Add Knowledge Search (Day 1)
**File:** `runner/orchestrator_assistant.py` (new)

```python
class OrchestratorAssistant:
    def search_knowledge(self, query: str) -> str:
        """Find similar outcomes from prior tasks."""
        # Use pgvector to search `knowledge` table
        # Return top 3 matches with code snippets
```

**Test:** Queue a task, have Claude Code call `orchestrator.search_knowledge(query)` mid-execution.

### Step 2: Update Runner to Use SDK (Day 1-2)
**File:** `runner/runner.py` (modify)

Replace:
```python
subprocess.run([CLAUDE_BIN, "python3", "runner.py", prompt])
```

With:
```python
from claude_code_agent import run_coding_agent_with_context
result = run_coding_agent_with_context(
    prompt=prompt,
    orchestrator=OrchestratorAssistant(...)
)
```

**File:** `runner/claude_code_agent.py` (new)
- Initialize Claude Code Agent with system prompt that includes orchestrator API
- Parse Claude's requests to call orchestrator functions
- Continue loop until agent says "DONE"

### Step 3: Add Ideation & Snippets (Day 2-3)
**Orchestrator methods:**
- `get_patterns(feature_type)` → "show me auth patterns used elsewhere"
- `get_snippets(context)` → "give me a working example of X"
- `ask_assistant(question)` → Quick Haiku call for unblocking

**Safety:** Auto-stop after 50 turns per task, 10 min timeout.

### Step 4: Test & Measure (Day 3)
**Test task:** "Add comprehensive error handling to X module"
- ✅ Does Claude Code search knowledge?
- ✅ Does it reuse code from outcomes?
- ✅ Does it ask for help if stuck?
- ✅ Does it run tests before committing?
- 📊 Measure: cost, time, success rate

## File Structure (After Integration)

```
runner/
├── runner.py                    (updated: use SDK instead of CLI wrapper)
├── claude_code_agent.py         (new: orchestrator integration)
├── orchestrator_assistant.py    (new: knowledge layer API)
├── account_pool.py              (existing: account rotation)
├── verify.py                    (existing: diff review)
└── .env.example                 (existing: secrets)
```

## Example: Claude Code Agent Making Decisions

**Scenario:** Task = "Add rate limiting to the API"

```
Claude Code Agent:
  1. Reads the prompt: "Add rate limiting to the API"
  2. Searches orchestrator knowledge: "rate limiting" + "API"
     → Finds 3 prior outcomes from other projects
     → Returns: working Redis-based solution + Redis-in-memory fallback
  3. Realizes it can reuse the Redis approach
  4. Implements in 5 minutes instead of 30 (copy-paste + test)
  5. Runs tests (all pass)
  6. Commits to worktree
  7. Reports back to orchestrator: "DONE. Reused pattern from outcome #123."

  → Cost: $0.02 (vs. $0.15 if rebuilding from scratch)
  → Time: 5 min (vs. 30 min)
  → Quality: Proven pattern (not new code)
```

## Decision Points

**For you to decide:**

1. **Model:** Opus 4.8 (smart but slower) vs. Sonnet 5 (faster but needs better prompting)?
   - Recommendation: Start with Sonnet 5, switch to Opus if agent struggles

2. **Knowledge ranking:** Sort by cost, recency, or success rate?
   - Recommendation: Cost (fastest/cheapest solutions first)

3. **Ideation budget:** How much should we spend on `ask_assistant()` per task?
   - Recommendation: Max $0.01 (1-2 Haiku calls max per task)

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Agent loops forever | Max 50 turns, 10 min timeout |
| Agent breaks code | Still verify diffs before merge |
| Agent commits bad code | Test gate: only commit if tests pass |
| Cost explosion | Per-project budget caps still enforced |
| Agent ignores knowledge | Log all calls; human can review agent's decisions |

## Timeline

| Phase | What | Time | Dependency |
|-------|------|------|------------|
| 0 | Verify current system works | 13 min | Complete ACTION 1-6 |
| 1 | Implement `search_knowledge()` | 1 day | Phase 0 done |
| 2 | Update runner to use SDK | 1 day | Phase 1 working |
| 3 | Add `ask_assistant()`, `get_snippets()` | 1 day | Phase 2 working |
| 4 | Test & measure on real tasks | 1 day | Phase 3 working |
| 5 | Rollout to all projects | Ongoing | Phase 4 successful |

**Total:** ~3-4 days to full integration (while keeping current system running in parallel).

## How to Start

1. **Finish ACTION 1-6** (baseline the current orchestrator)
2. **Read** `CLAUDE-CODE-INTEGRATION.md` (full architecture)
3. **Create** `runner/orchestrator_assistant.py` (start with `search_knowledge()` only)
4. **Test** on 1 small task
5. **Measure** cost/time savings
6. **Iterate**

## Success Metrics

After integration, we should see:

- ✅ **Cost:** ~50% reduction in Claude API spend (reuse patterns)
- ✅ **Speed:** ~2x faster task execution (don't rebuild from scratch)
- ✅ **Quality:** Higher success rate (proven patterns, less experimentation)
- ✅ **Learning:** Self-improving loop detects which patterns work best
- ✅ **Cross-project:** Solutions from Tomorrow automatically benefit Smarter/Apparently

---

**Next Action:** Complete ACTION 1-6 of READY-FOR-SETUP.md first, then revisit this roadmap for Phase 1 implementation.

This is the orchestrator's next evolution: from task runner → intelligent coding assistant.
