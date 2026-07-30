# Multi-Vendor Coding Agent Architecture

The orchestrator should support **any coding agent** (Claude Code, OpenAI o1, Anthropic, etc.) working the same way: **direct repo implementation + real-time remediation** with orchestrator assistance.

## Core Principle

All agents (vendor-agnostic) should:
1. **Execute directly in worktree** (not isolated)
2. **Test in real-time** (run tests, see failures, fix immediately)
3. **Remediate on error** (don't give up; auto-fix and retry)
4. **Ask for help** (call orchestrator assistant if stuck)
5. **Commit when confident** (verified by tests, not just reviews)

## Multi-Vendor Abstraction Layer

```
┌──────────────────────────────────────────────────────┐
│ Runner (Vendor-Agnostic Orchestrator)                │
│                                                      │
│  ├─ Polls Supabase for task                         │
│  ├─ Creates git worktree                            │
│  ├─ Selects coding agent (Claude / OpenAI / etc)    │
│  └─ Initializes AgentExecutor (abstracted)          │
└──────────────────┬───────────────────────────────────┘
                   │
        ┌──────────┴────────────┬──────────────┐
        ↓                       ↓              ↓
    ┌────────────┐       ┌──────────┐   ┌──────────┐
    │ Claude     │       │ OpenAI   │   │ Anthropic│
    │ Code Agent │       │ o1 Agent │   │ Research │
    │            │       │          │   │ Agent    │
    │ (SDK)      │       │ (API)    │   │ (API)    │
    └────┬───────┘       └────┬─────┘   └────┬─────┘
         │                    │             │
         └────────────────┬───┴─────────────┘
                          │
                 ┌────────▼────────┐
                 │ AgentInterface   │
                 │ (Common contract)│
                 │                  │
                 │ ├─ execute()     │
                 │ ├─ test()        │
                 │ ├─ commit()      │
                 │ ├─ ask_help()    │
                 │ └─ rollback()    │
                 └────────┬─────────┘
                          │
                 ┌────────▼────────┐
                 │ Orchestrator     │
                 │ Assistant Layer  │
                 │                  │
                 │ ├─ search_code() │
                 │ ├─ get_patterns()│
                 │ ├─ ideate()      │
                 │ └─ snippets()    │
                 └──────────────────┘
```

## AgentInterface (Vendor-Agnostic Contract)

```python
from abc import ABC, abstractmethod

class CodingAgent(ABC):
    """Interface all coding agents must implement."""
    
    @abstractmethod
    def initialize(self, task: str, worktree_path: str, context: dict) -> None:
        """Initialize agent with task and context."""
        pass
    
    @abstractmethod
    def execute(self) -> dict:
        """Execute the task. Return: {status, code, files_changed}."""
        pass
    
    @abstractmethod
    def run_tests(self, test_cmd: str) -> dict:
        """Run tests. Return: {passed: bool, output: str, failures: []}."""
        pass
    
    @abstractmethod
    def remediate_error(self, error: str) -> dict:
        """Auto-fix error. Return: {status, attempt_num, fixes_applied}."""
        pass
    
    @abstractmethod
    def ask_orchestrator(self, question: str) -> str:
        """Ask orchestrator assistant for help."""
        pass
    
    @abstractmethod
    def commit_changes(self, message: str) -> dict:
        """Commit to worktree. Return: {commit_hash, status}."""
        pass
    
    @abstractmethod
    def rollback(self) -> dict:
        """Rollback all changes. Return: {status, files_restored}."""
        pass
```

## Vendor-Specific Implementations

### 1. Claude Code Agent (SDK)

```python
from anthropic import Anthropic

class ClaudeCodeAgent(CodingAgent):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-opus-4-8"  # Full reasoning
        self.messages = []
    
    def execute(self) -> dict:
        """Use Claude Code SDK to execute in worktree."""
        system_prompt = self._build_system_prompt()
        
        for turn in range(50):  # Max 50 turns
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=self.messages
            )
            
            assistant_text = response.content[0].text
            self.messages.append({"role": "assistant", "content": assistant_text})
            
            # Parse assistant's action
            if "DONE" in assistant_text or "commit" in assistant_text.lower():
                return {"status": "success", "code": self._extract_code()}
            
            elif "test_results" in assistant_text:
                # Run tests and report back
                tests = self._run_tests()
                self.messages.append({"role": "user", "content": f"Test results:\n{tests}"})
            
            elif "orchestrator.search_code" in assistant_text:
                # Call orchestrator knowledge layer
                knowledge = self._query_orchestrator(assistant_text)
                self.messages.append({"role": "user", "content": f"Code suggestions:\n{knowledge}"})
            
            else:
                # Continue executing
                self.messages.append({"role": "user", "content": "Continue executing."})
        
        return {"status": "max_turns_reached"}
    
    def remediate_error(self, error: str) -> dict:
        """Claude automatically fixes errors in next turn."""
        self.messages.append({
            "role": "user",
            "content": f"Error occurred:\n{error}\n\nFix this and retry."
        })
        # Next call to execute() will attempt fix
        return {"status": "remedy_proposed", "attempt_num": len(self.messages)}
```

### 2. OpenAI o1 Agent (API)

```python
import openai

class OpenAI_O1_Agent(CodingAgent):
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = "o1"  # Deep thinking, step-by-step
    
    def execute(self) -> dict:
        """Use o1 for complex reasoning before coding."""
        # o1 is best for thinking, then implementing
        # Use iterative loops: think → code → test → refine
        
        planning_response = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": f"Think deeply about this problem:\n{self.task}\n\nThen provide a step-by-step implementation plan."
            }]
        )
        
        plan = planning_response.choices[0].message.content
        
        # Now implement based on plan
        impl_response = self.client.chat.completions.create(
            model="gpt-4",  # Use faster model for implementation
            messages=[
                {"role": "user", "content": f"Plan:\n{plan}"},
                {"role": "user", "content": "Now implement this plan in the worktree."}
            ]
        )
        
        return {"status": "success", "plan": plan, "code": impl_response.choices[0].message.content}
    
    def remediate_error(self, error: str) -> dict:
        """Use o1 to think through error fix deeply."""
        fix_response = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": f"I got this error:\n{error}\n\nThink deeply about root cause and fix."
            }]
        )
        return {"status": "remedy_proposed", "fix": fix_response.choices[0].message.content}
```

### 3. Anthropic Research Agent (Advanced)

```python
from anthropic import Anthropic

class AnthropicResearchAgent(CodingAgent):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-opus-4-8"
    
    def execute(self) -> dict:
        """Deep research + implementation + verification."""
        # 1. Research phase: understand problem deeply
        research = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"Research and explain:\n{self.task}"
            }]
        )
        
        # 2. Implementation phase: code based on research
        impl = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "user", "content": research.content[0].text},
                {"role": "user", "content": "Now implement in the worktree."}
            ]
        )
        
        # 3. Verification phase: test and validate
        tests = self._run_tests()
        
        if tests.get("passed"):
            return {"status": "success", "research": research.content[0].text, "code": impl.content[0].text}
        else:
            return {"status": "tests_failed", "failures": tests.get("failures", [])}
```

## Runner (Vendor Selection Logic)

```python
def get_agent(vendor: str, api_key: str) -> CodingAgent:
    """Factory to select coding agent."""
    agents = {
        "claude": ClaudeCodeAgent,
        "openai_o1": OpenAI_O1_Agent,
        "anthropic_research": AnthropicResearchAgent,
        # Add more vendors as needed
    }
    return agents[vendor](api_key)

def execute_task(task_id: str, vendor: str = "claude"):
    """Execute task with specified coding agent."""
    
    # Load vendor's API key from account_pool
    api_key = account_pool.get_api_key(vendor)
    
    # Select agent
    agent = get_agent(vendor, api_key)
    
    # Initialize
    agent.initialize(
        task=task["prompt"],
        worktree_path=task["worktree"],
        context=orchestrator.get_context()  # Knowledge + patterns
    )
    
    # Execute with auto-remediation loop
    attempt = 0
    while attempt < 3:
        result = agent.execute()
        tests = agent.run_tests()
        
        if tests.get("passed"):
            # Success: commit and return
            agent.commit_changes(f"Task {task_id}: {task['prompt'][:50]}...")
            return {"status": "success", "agent": vendor, "cost": ..., "time": ...}
        
        else:
            # Failed: remediate and retry
            error = tests.get("failures", "Unknown error")[0]
            agent.remediate_error(error)
            attempt += 1
    
    # All attempts failed: create approval card
    return {"status": "approval_needed", "reason": "All auto-fix attempts failed"}
```

## Routing Logic (Which Agent to Use?)

```python
def select_agent_for_task(task: dict) -> str:
    """Select best agent based on task characteristics."""
    
    prompt = task["prompt"].lower()
    
    # Rules (can be learned over time)
    if "test" in prompt or "verify" in prompt:
        return "claude"  # Claude best at testing
    
    elif "deep" in prompt or "research" in prompt or "complex" in prompt:
        return "openai_o1"  # o1 best at deep thinking
    
    elif "refactor" in prompt or "optimize" in prompt:
        return "anthropic_research"  # Research agent best at systematic improvement
    
    else:
        return "claude"  # Default: Claude (most balanced)
```

## Orchestrator Assists All Vendors

**orchestrator/universal_assistant.py:**

```python
class UniversalOrchestratorAssistant:
    """Works with any coding agent (vendor-agnostic)."""
    
    def search_code(self, query: str, vendor: str = None) -> str:
        """Search across all prior outcomes (regardless of vendor)."""
        # pgvector search
        results = self.db.rpc('match_knowledge', {'query': query}).execute()
        return self._format_for_agent(results, vendor)
    
    def get_patterns(self, feature: str, vendor: str = None) -> str:
        """Get patterns (formatted for specific agent if needed)."""
        patterns = self.db.table('knowledge').select('*').match(
            {'feature_type': feature}
        ).execute()
        return self._format_for_agent(patterns, vendor)
    
    def ideate(self, question: str, vendor: str = None) -> str:
        """Ask for ideation (use fastest model for quick help)."""
        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap
            messages=[{"role": "user", "content": question}]
        )
        return response.content[0].text
    
    def _format_for_agent(self, data: dict, vendor: str) -> str:
        """Format results based on vendor's preferences."""
        if vendor == "openai_o1":
            # o1 prefers structured reasoning chains
            return self._format_as_reasoning_chain(data)
        elif vendor == "anthropic_research":
            # Research agent prefers detailed analysis
            return self._format_as_analysis(data)
        else:
            # Default: JSON
            return json.dumps(data, indent=2)
```

## Benefits of Multi-Vendor Approach

| Benefit | How |
|---------|-----|
| **Vendor Flexibility** | Use best agent for each task type |
| **Cost Optimization** | Route expensive tasks to o1, cheap tasks to Claude |
| **Redundancy** | If one vendor down, use another |
| **Cross-Learning** | o1's research informs Claude's implementation |
| **Continuous Improvement** | Learn which agents work best for what |

## Rollout Timeline

| Phase | What | Time |
|-------|------|------|
| 1 | Claude Code + Orchestrator (current) | 2-3 days |
| 2 | Add OpenAI o1 agent (multi-vendor abstraction) | 2-3 days |
| 3 | Add Anthropic Research agent | 1-2 days |
| 4 | Smart routing (select best agent per task) | 1 week (learning) |
| 5 | Cross-vendor knowledge sharing | Ongoing |

## Configuration (vendor/.env)

```bash
# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-proj-...
ANTHROPIC_API_KEY_2=sk-proj-...  # Rotation account 2
ANTHROPIC_API_KEY_3=sk-proj-...  # Rotation account 3

# OpenAI (o1, GPT-4)
OPENAI_API_KEY=sk-...
OPENAI_API_KEY_2=sk-...  # Fallback

# Other vendors (future)
GROQ_API_KEY=...
FIREWORKS_API_KEY=...
```

**Runner selects vendor based on:**
- Task characteristics (complexity, type)
- Cost constraints (budget cap)
- Model preferences per-project
- Vendor availability (fallback)

## Result: Intelligent Poly-Agent Orchestrator

Instead of: "Always use Claude"

You get: "Use o1 for hard thinking, Claude for implementation, Claude Code for testing, Anthropic Research for optimization, depending on what works best"

All agents:
- Execute directly in repo (no isolation)
- Test in real-time (see failures, fix immediately)
- Call orchestrator for help (search code, patterns, ideation)
- Learn from all prior outcomes (cross-vendor knowledge)
- Report transparently (cost, time, model used)

---

**Next Step:** Implement multi-vendor abstraction after Phase 0 baseline (finish ACTION 1-6 first).
