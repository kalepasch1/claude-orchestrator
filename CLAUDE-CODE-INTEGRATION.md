# Claude Code Integration — Enhanced Orchestrator Architecture

This document outlines how to deeply integrate Claude Code as the orchestrator's execution engine, with real-time two-way communication for ideation, context retrieval, and pattern matching.

## Current State vs. Desired State

### Current Flow (Runner Wrapper)
```
1. Runner polls Supabase for task
2. Runner calls: CLAUDE_BIN=claude python3 runner.py [prompt]
3. Claude Code runs in worktree (isolation)
4. Runner verifies diff, integrates, records outcome
```

**Gap:** Claude Code is isolated; can't access orchestrator's knowledge layer, ongoing context, or ask for help mid-execution.

### Desired Flow (Orchestrator + Claude Code Integration)
```
1. Runner polls Supabase for task
2. Runner initializes Claude Code SDK (not CLI wrapper)
3. Claude Code Agent starts in worktree with:
   ├─ Full orchestrator context (knowledge embeddings, prior outcomes)
   ├─ Two-way communication channel to orchestrator
   └─ Access to snippet library (don't reinvent)
4. While executing:
   ├─ Can call orchestrator.search_knowledge() → semantic solutions
   ├─ Can call orchestrator.get_patterns() → common approaches
   ├─ Can call orchestrator.ask_assistant() → real-time ideation
   └─ Can fetch ready-made code snippets from successful outcomes
5. Tests in real-time, commits when confident, auto-recovers on error
6. Orchestrator records: outcome + improvements + learned patterns
```

## Architecture: Orchestrator as Assistant Layer

```
┌─────────────────────────────────────────────────────────────┐
│ Web Dashboard (Vercel)                                      │
│  ├─ Queue task                                              │
│  ├─ Approve risky changes                                   │
│  └─ Monitor spend + account rotation                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
        ┌────────────────────────────┐
        │ Supabase (Task Queue)      │
        │ ├─ tasks (pending/running) │
        │ ├─ outcomes (results)      │
        │ └─ knowledge (embeddings)  │
        └────────────┬───────────────┘
                     │
                     ↓
    ┌────────────────────────────────────────┐
    │ Runner (Python on your Mac)            │
    │ ├─ Polls Supabase every 5 sec         │
    │ ├─ Creates git worktree               │
    │ └─ Initializes Claude Code Agent  ←──┐│
    └────────────────┬──────────────────────┘│
                     │                        │
                     ↓                        │ Initialization
    ┌────────────────────────────────────────┐│ only
    │ Claude Code Agent (Interactive)        ││
    │ ├─ Reads codebase in worktree         ││
    │ ├─ Understands task prompt            ││
    │ └─ ← → Two-way communication ────────┼┘
    │      (while executing)                │
    │                                        │
    │ During execution:                      │
    │ ├─ orchestrator.search_knowledge()     │ Real-time
    │ │   ↓ (what similar code exists?)     │ context
    │ ├─ orchestrator.get_patterns()         │ & help
    │ │   ↓ (what's the best approach?)     │
    │ ├─ orchestrator.ask_assistant()        │
    │ │   ↓ (ideation/unblock)               │
    │ └─ orchestrator.get_snippets()         │
    │     ↓ (reuse from outcomes)            │
    │                                        │
    │ ├─ Run tests (real-time)               │
    │ ├─ Commit if passing                   │
    │ ├─ Auto-recover on error               │
    │ └─ Report back to runner               │
    └────────────────┬─────────────────────┘
                     │
                     ↓
    ┌────────────────────────────────────────┐
    │ Orchestrator Verification              │
    │ ├─ Verify diff (cheap model)           │
    │ ├─ Approve or create card              │
    │ └─ Integrate to main                   │
    └────────────────┬──────────────────────┘
                     │
                     ↓
    ┌────────────────────────────────────────┐
    │ Supabase Outcome Recording             │
    │ ├─ cost, tokens, time                  │
    │ ├─ learned patterns                    │
    │ └─ embeddings for future reuse         │
    └────────────────────────────────────────┘
```

## Implementation: Claude Code SDK Integration

### 1. Replace CLI Wrapper with SDK Initialization

**Current (runner.py):**
```python
import subprocess
result = subprocess.run(
    [CLAUDE_BIN, "python3", "runner.py", prompt],
    cwd=worktree_path,
    capture_output=True
)
```

**Desired (runner.py with SDK):**
```python
from anthropic import Anthropic
import os

def initialize_coding_agent(prompt, project_repo, orchestrator_context):
    """Initialize Claude Code Agent with orchestrator knowledge layer."""

    client = Anthropic(
        api_key=os.getenv('ANTHROPIC_API_KEY'),
        timeout=600  # 10 min timeout for long-running tasks
    )

    # System prompt includes orchestrator integration
    system_prompt = f"""
You are a coding agent executing a task for the {project_repo} repository.

**Task:** {prompt}

**Available Orchestrator Functions (call during execution):**

1. orchestrator.search_knowledge(query)
   → Semantic search of prior outcomes + solutions
   → Use: "find similar code patterns for X"
   → Returns: matching snippets + context

2. orchestrator.get_patterns(feature_type)
   → Fetch common approaches (e.g., "auth", "caching", "testing")
   → Use: "what's the standard pattern for Y?"
   → Returns: best practices + code examples

3. orchestrator.ask_assistant(question)
   → Real-time ideation/help while executing
   → Use: "I'm stuck on X, what should I try?"
   → Returns: suggestions + code sketches

4. orchestrator.get_snippets(context)
   → Fetch ready-made code from successful outcomes
   → Use: "show me working example of Z"
   → Returns: vetted, tested code

**Workflow:**
1. Understand the task
2. Search orchestrator knowledge (don't reinvent)
3. Read relevant code in worktree
4. Code iteratively, test in real-time
5. When confident, commit + report back
6. If stuck, ask orchestrator assistant
7. Auto-recover on errors, propose fixes

**Test as you code:** Run tests frequently, fix failures immediately.

**Report format (when done):**
- What was built
- Tests passing: [yes/no]
- Commit hash: [hash]
- Time taken
- Learnings for future tasks
"""

    messages = [
        {
            "role": "user",
            "content": system_prompt + f"\n\n**Now execute this task:**\n{prompt}"
        }
    ]

    # Start interactive session
    return client, messages

def run_coding_agent(client, messages, orchestrator, worktree_path):
    """Run Claude Code Agent with two-way orchestrator communication."""

    max_turns = 50
    for turn in range(max_turns):
        # Get Claude's next action/code/question
        response = client.messages.create(
            model="claude-opus-4-8",  # Use full Opus for complex reasoning
            max_tokens=4096,
            system="You are a coding agent in a git worktree. Execute code, run tests, and commit changes.",
            messages=messages
        )

        assistant_message = response.content[0].text
        messages.append({"role": "assistant", "content": assistant_message})

        # Parse assistant's request (if calling orchestrator functions)
        if "orchestrator.search_knowledge" in assistant_message:
            query = extract_query(assistant_message)
            knowledge = orchestrator.search_knowledge(query)
            context = f"Knowledge search results:\n{knowledge}"

        elif "orchestrator.get_patterns" in assistant_message:
            feature = extract_feature(assistant_message)
            patterns = orchestrator.get_patterns(feature)
            context = f"Patterns for {feature}:\n{patterns}"

        elif "orchestrator.ask_assistant" in assistant_message:
            question = extract_question(assistant_message)
            advice = orchestrator.ask_assistant(question)
            context = f"Assistant advice:\n{advice}"

        elif "orchestrator.get_snippets" in assistant_message:
            snippet_context = extract_context(assistant_message)
            snippets = orchestrator.get_snippets(snippet_context)
            context = f"Code snippets:\n{snippets}"

        elif "DONE" in assistant_message or "commit" in assistant_message.lower():
            # Agent is done; extract results
            return parse_final_report(assistant_message)

        else:
            # Assistant is coding/testing; add context for next turn
            context = f"Continue executing in {worktree_path}. Run tests, fix errors, iterate."

        # Add orchestrator context to messages and continue
        messages.append({"role": "user", "content": context})

    # Max turns reached; capture partial result
    return parse_final_report(messages[-1]["content"])
```

### 2. Orchestrator Knowledge Layer (Backend)

**orchestrator/knowledge_assistant.py:**
```python
import json
from anthropic import Anthropic
from supabase import create_client

class OrchestratorAssistant:
    """Assist Claude Code Agent during task execution."""

    def __init__(self, supabase_url, service_key):
        self.db = create_client(supabase_url, service_key)
        self.claude = Anthropic()

    def search_knowledge(self, query: str) -> str:
        """Semantic search of prior outcomes + solutions."""
        # Use pgvector to find similar outcomes
        results = self.db.rpc(
            'match_knowledge',
            {'query_text': query, 'similarity_threshold': 0.7}
        ).execute()

        # Format results for Claude
        snippets = []
        for outcome in results.data[:3]:  # Top 3 matches
            snippets.append({
                'task': outcome['task_prompt'],
                'solution': outcome['code_summary'],
                'cost': outcome['cost'],
                'passed': outcome['tests_passed']
            })

        return json.dumps(snippets, indent=2)

    def get_patterns(self, feature_type: str) -> str:
        """Fetch common approaches for a feature type."""
        # Query outcomes tagged with this feature
        patterns = self.db.table('knowledge').select(
            'code_summary, pattern_name'
        ).match({'feature_type': feature_type}).execute()

        return json.dumps(patterns.data[:5], indent=2)

    def ask_assistant(self, question: str) -> str:
        """Real-time ideation/help (quick Haiku call)."""
        response = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast, cheap
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": f"You are helping a coding agent. Answer briefly:\n{question}"
                }
            ]
        )
        return response.content[0].text

    def get_snippets(self, context: str) -> str:
        """Fetch ready-made code from successful outcomes."""
        # Search for code snippets matching context
        results = self.db.table('outcomes').select(
            'code_snippet, test_results'
        ).filter('code_snippet', 'is.not', None).order(
            'cost', ascending=True  # Cheapest/simplest first
        ).limit(3).execute()

        snippets = []
        for outcome in results.data:
            if outcome['test_results'] and outcome['test_results'].get('passed'):
                snippets.append(outcome['code_snippet'])

        return '\n\n'.join(snippets) if snippets else "No matching snippets found."
```

### 3. Runner Integration

**runner/runner.py (enhanced):**
```python
import os
from knowledge_assistant import OrchestratorAssistant
from claude_code_agent import initialize_coding_agent, run_coding_agent

def execute_task_with_claude_code(task_id, prompt, project_repo, worktree_path):
    """Execute task using Claude Code Agent + orchestrator knowledge."""

    # Initialize orchestrator knowledge layer
    orchestrator = OrchestratorAssistant(
        supabase_url=os.getenv('SUPABASE_URL'),
        service_key=os.getenv('SUPABASE_SERVICE_KEY')
    )

    # Initialize Claude Code Agent
    client, messages = initialize_coding_agent(
        prompt=prompt,
        project_repo=project_repo,
        orchestrator_context=orchestrator
    )

    # Run agent with real-time orchestrator communication
    result = run_coding_agent(
        client=client,
        messages=messages,
        orchestrator=orchestrator,
        worktree_path=worktree_path
    )

    # Record outcome + learnings
    record_outcome(
        task_id=task_id,
        result=result,
        orchestrator_calls=result.get('orchestrator_stats', {})
    )

    return result
```

## Benefits of This Architecture

| Benefit | How |
|---------|-----|
| **No Reinvention** | Claude Code searches orchestrator knowledge before coding |
| **Real-Time Help** | Can ask for ideation/unblocking mid-execution (fast Haiku calls) |
| **Snippet Reuse** | Access proven, tested code from prior outcomes |
| **Cross-Project Learning** | Solutions from Tomorrow help Smarter/Apparently |
| **Cost Savings** | Reuse patterns instead of generating new code each time |
| **Transparency** | All orchestrator calls logged; can audit agent's reasoning |
| **Self-Improvement** | Learn which orchestrator functions help most; optimize prompting |

## Rollout Plan

### Phase 1: Basic Integration (1-2 weeks)
- [ ] Replace CLI wrapper with SDK initialization
- [ ] Implement `orchestrator.search_knowledge()` only
- [ ] Test on 10 tasks (Tomorrow project)
- [ ] Measure: cost savings, execution time

### Phase 2: Add Ideation (1 week)
- [ ] Implement `orchestrator.ask_assistant()` (Haiku calls)
- [ ] Test on complex tasks (Smarter project)
- [ ] Add timeout/auto-recovery for stuck agents

### Phase 3: Snippet Reuse (1 week)
- [ ] Implement `orchestrator.get_snippets()`
- [ ] Tag outcomes with feature types + patterns
- [ ] Test on Apparently (core tech — more reusable patterns)

### Phase 4: Self-Improvement Loop (Ongoing)
- [ ] Track which orchestrator calls helped most
- [ ] Optimize prompt based on learnings
- [ ] A/B test different integration strategies

## Safety Guardrails

**To prevent agent runaway:**
1. **Max turns:** 50 turns per task (auto-stop)
2. **Timeout:** 10 min per task (auto-kill agent)
3. **Test gate:** Only commit if tests pass
4. **Approval required:** Risky diffs still need human review
5. **Cost cap:** Per-project budget still enforced
6. **Dry-run mode:** Test without committing first

## Open Questions

1. **Model choice for agent:** Should we use Opus 4.8 (expensive, smart) or Sonnet 5 (cheaper, fast)?
2. **Orchestrator response time:** How to keep ideation fast (Haiku) without oversimplifying?
3. **Knowledge search:** Should we rank by cost, recency, or success rate?
4. **Multi-turn limit:** Is 50 turns enough? Should it be project-dependent?

---

## Next Steps

1. Implement `orchestrator.search_knowledge()` first (lowest risk, highest value)
2. Test on a small Tomorrow task (e.g., "add docstring to 5 functions")
3. Measure: Does it reuse code? How much does it save?
4. Iterate based on results

This architecture transforms the orchestrator from a "task runner" into a true "coding assistant" that learns from experience and helps Claude Code agents execute faster, cheaper, and better.
