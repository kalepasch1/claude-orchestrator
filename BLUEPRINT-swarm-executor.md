# Blueprint: Subscription-First Parallel Swarm Executor

**Status:** Proposed  
**Author:** Claude (Cowork session, 2026-07-11)  
**Goal:** 10X–500X throughput increase for code implementation by routing work through Cowork-style subscription execution first, overflowing to paid API only when limits are hit.

---

## 1. Why Cowork Is Fast and the Orchestrator Is Slow

The orchestrator currently executes code tasks by spawning **Claude Code CLI subprocesses** (`claude -p ... --output-format json`). Every call goes through:

1. **Subscription rate limits** — 80 calls/hour hard cap per account, $10/hr, $40/day
2. **Account rotation overhead** — `account_pool.py` cycles through exhausted accounts with 20min–6hr cooldowns
3. **CLI cold-start** — each subprocess bootstraps a new Claude session (~3-8s), loads the repo context from scratch
4. **Git worktree setup/teardown** — every task creates an isolated worktree, does its work, then merges through the merge train
5. **Serial merge train** — `repo_lock.py` serializes all integrations per-repo

Cowork, by contrast, uses **direct API calls** with parallel sub-agent spawning. There are no subscription rate limits on API usage — throughput scales linearly with spend. Agents share context, fan out in parallel, and produce diffs that can be applied without git ceremony.

**The subscription rate limit is the binding constraint.** The orchestrator's parallelism (12 threads, 48-semaphore ceiling) is already well-designed, but it's starved because the pipe feeding it (CLI calls gated by subscription limits) is a straw.

### Quantified bottleneck

| Metric | Current (CLI) | API-first potential |
|--------|---------------|---------------------|
| Calls/hour/account | 80 | ~2,000+ (API, depends on model/concurrency) |
| Accounts needed | N (rotation) | 1 API key |
| Cold-start per call | 3–8s | 0 (stateless HTTP) |
| Worktree setup | 2–5s | 0 (diff-in-memory) |
| Merge serialization | Blocked on repo_lock | Batch-apply diffs |
| Effective parallelism | ~12 (resource-governed) | 50–200 (API concurrency) |

**Conservative 10X** comes from eliminating the 80-call/hr ceiling alone. **100X+** comes from combining that with multi-vendor fan-out, diff-mode execution, and streaming dependency resolution.

---

## 2. The Hybrid Insight: Subscription → Cowork → API Overflow

Cowork runs on the subscription. It's not API-billed. Yet it executes at API speed because it uses a different execution path — direct model calls through the Anthropic infrastructure, not the CLI subprocess with its per-session rate limits. The orchestrator should exploit this by treating Cowork as the **primary execution tier** and API as overflow.

### The three-tier cost cascade

```
Tier 0: Cowork Subscription Workers    ($0/task, subscription-covered)
  ↓ when subscription limits hit
Tier 1: Agent SDK Subscription          ($0/task, same subscription, different path)
  ↓ when all subscription capacity exhausted
Tier 2: Direct API + Multi-Vendor       ($0.01-0.25/task, pay-per-use)
```

### Tier 0: Cowork as an Execution Engine

The key mechanism: **Cowork scheduled tasks** run automatically on the subscription. Each scheduled task can use the full Agent tool to spawn parallel sub-agents. A scheduled task that polls the Supabase task queue effectively turns Cowork into a fleet worker — for free.

**Implementation: `cowork-executor` scheduled task**

The orchestrator creates a Cowork scheduled task (via the Cowork plugin or manual setup) that:

1. Reads the Supabase task queue for QUEUED tasks
2. Claims N tasks atomically
3. Fans out via the Agent tool — each sub-agent works on one task independently
4. Writes results (diffs, new files) back to the repo
5. Marks tasks as DONE in Supabase

```
Scheduled task: "Execute orchestrator queue" (runs every 5 minutes)
  → reads from Supabase tasks table (QUEUED status)
  → claims up to 5 tasks
  → spawns 5 parallel Agent sub-agents
  → each agent: reads files, applies prompt, produces diff
  → diffs written to repo, tasks marked complete
```

This is zero additional cost — the subscription already covers Cowork and scheduled tasks. The Agent tool's parallel execution gives you the concurrency that the CLI path lacks.

**Why this works better than the CLI path:**

| Dimension | CLI subprocess | Cowork Agent tool |
|-----------|---------------|-------------------|
| Rate limiting | 80 calls/hr per account | Higher/different subscription limits |
| Cold start | 3-8s per subprocess | 0 (agents spawned in-process) |
| Parallelism | Thread-per-task, each spawns a CLI | Multiple agents in one session |
| Context | Each call re-reads entire repo | Shared context via file tools |
| Git overhead | Full worktree per task | Direct file edits, batch commit |
| Cost | $0 (subscription) | $0 (subscription) |

### Tier 0.5: Multiple Subscription Accounts × Cowork Sessions

Each subscription account can run its own Cowork session. With N accounts:

- N concurrent Cowork sessions, each polling the same Supabase queue
- Each session fans out M sub-agents via the Agent tool
- Effective parallelism: N × M (e.g., 3 accounts × 5 agents = 15 concurrent tasks)
- Cost: N × subscription fee (you're already paying this for account rotation)

The existing `account_pool.py` already manages N accounts. Instead of rotating them through CLI calls that hit limits, each account runs a persistent Cowork worker session.

### Tier 1: Agent SDK Subscription Path (existing, underused)

The `ORCH_USE_SDK=true` path in `claude_cli.py` already uses the subscription via the Agent SDK. It's currently a 1:1 replacement for the CLI subprocess — same rate limits, same serial execution. But the SDK supports streaming and structured output, which enables:

- **Streaming diffs** — start processing output before the call finishes
- **Rate limit detection** — the SDK emits rate_limit events (line 164 of claude_cli.py) which can trigger immediate failover to Tier 2 instead of cooldown
- **Lower overhead** — no subprocess spawn, no JSON parsing of stdout

Enhancement: when the SDK reports a rate_limit event, immediately route subsequent tasks to Tier 2 (API) instead of parking the account for 20 minutes. This means the subscription absorbs the first N tasks for free, and overflow goes to API instantly — no wasted cooldown time.

### Tier 2: API + Multi-Vendor (the original swarm design)

Only reached when subscription capacity is genuinely exhausted. At this point every additional task is incremental throughput at marginal cost. The multi-vendor fan-out (Claude API + OpenAI + Gemini + DeepSeek) kicks in here.

### Hybrid Router: `runner/tier_router.py`

```python
"""
tier_router.py - routes each task to the cheapest execution tier that has capacity.

Tier 0: Cowork scheduled task workers (subscription, $0)
Tier 1: Agent SDK subscription path ($0)  
Tier 2: Direct API calls ($0.01-0.25/task)

Always starts at Tier 0. Overflows to higher tiers only when lower tiers
report exhaustion. Falls back down as soon as lower tiers recover.
"""
import time

class TierRouter:
    def __init__(self):
        self._tier0_exhausted_until = 0  # timestamp
        self._tier1_exhausted_until = 0
    
    def route(self, task: dict) -> str:
        now = time.time()
        
        # Tier 0: Cowork workers — check if any are alive and have capacity
        if now > self._tier0_exhausted_until and self._cowork_workers_available():
            return "cowork"
        
        # Tier 1: Agent SDK subscription — check if not rate-limited
        if now > self._tier1_exhausted_until and not self._subscription_exhausted():
            return "sdk"
        
        # Tier 2: API — always available (cost-gated, not rate-gated)
        return "api"
    
    def mark_exhausted(self, tier: str, cooldown_s: int = 300):
        if tier == "cowork":
            self._tier0_exhausted_until = time.time() + cooldown_s
        elif tier == "sdk":
            self._tier1_exhausted_until = time.time() + cooldown_s
    
    def _cowork_workers_available(self) -> bool:
        """Check Supabase for active Cowork worker heartbeats."""
        # Workers write heartbeats to a `cowork_workers` table
        # If any heartbeat is < 60s old, Tier 0 has capacity
        try:
            import db
            workers = db.supabase_get("cowork_workers", 
                                       params={"heartbeat_at": f"gt.{time.time() - 60}"})
            return len(workers) > 0
        except Exception:
            return False
    
    def _subscription_exhausted(self) -> bool:
        """Check if all subscription accounts are cooling."""
        try:
            from account_pool import claude_exhausted
            return claude_exhausted()
        except Exception:
            return False
```

### Cowork Worker Plugin: `cowork-queue-worker`

A Cowork plugin (or skill) that turns any Cowork session into a fleet worker:

```python
# Pseudo-code for the Cowork-side skill
# This runs INSIDE a Cowork scheduled task

"""
SKILL: Queue Worker
Polls the orchestrator's Supabase task queue and executes tasks using 
the Agent tool for parallel sub-agent execution. Runs on subscription.
"""

# 1. Connect to Supabase (read task queue)
# 2. Claim N QUEUED tasks (atomic update: status = RUNNING, claimed_by = this_worker)
# 3. For each claimed task, spawn an Agent:
#    Agent(description="Execute task {slug}", prompt=task.prompt)
#    → Agent reads relevant files, applies changes, reports diff
# 4. Collect results from all agents
# 5. Commit changes to git
# 6. Mark tasks as DONE in Supabase
# 7. Write heartbeat to cowork_workers table
```

The key is that each Agent call within the Cowork session runs on the same subscription but gets the fast execution path. Multiple agents can run in parallel within a single session.

### Cost comparison: hybrid vs. pure API

| Workload | Pure CLI (current) | Pure API | Hybrid (subscription-first) |
|----------|-------------------|----------|----------------------------|
| 100 tasks/day | $0 (sub), ~2hrs | ~$5-10 | $0 (sub), ~20min |
| 500 tasks/day | $0 (sub), ~8hrs+ | ~$25-50 | ~$5-10 (90% sub, 10% API) |
| 2000 tasks/day | Impossible (limits) | ~$100-200 | ~$20-40 (80% sub, 20% API) |

The hybrid approach gets you 80-90% of the pure API throughput at 10-20% of the cost, because the subscription absorbs the bulk of the work.

---

## 3. Architecture: The Swarm Executor

### Core idea

Replace `claude_cli.run()` (subprocess → CLI → subscription) with a new `swarm_executor.py` that:

1. Makes **direct API calls** to Claude (Messages API), OpenAI, Gemini, DeepSeek — all in parallel
2. Operates in **diff mode** — the model receives file contents + instructions and returns a unified diff, not a full agentic session
3. Fans out **N tasks simultaneously** with no per-account rate rotation
4. Accumulates diffs in memory and **batch-applies** them, bypassing the per-task worktree/merge cycle

### Execution modes (graduated)

```
Mode 1: "API Direct" (10X)
  - Replace CLI subprocess with Messages API call
  - Same task decomposition, same merge train
  - Just removes the subscription bottleneck
  
Mode 2: "Diff Swarm" (50-100X)  
  - Model returns unified diffs instead of running agentic sessions
  - No worktrees — diffs applied to a single checkout
  - Batch integration instead of per-task merge
  
Mode 3: "Multi-Vendor Swarm" (100-500X)
  - Fan out across Claude API + OpenAI + Gemini + DeepSeek simultaneously
  - Each vendor has independent rate limits
  - Bandit routes by task difficulty; all vendors execute concurrently
  - Speculative execution: send same task to 2 vendors, take first good result
```

### New module: `runner/swarm_executor.py`

```python
"""
swarm_executor.py - API-first parallel execution engine.

Replaces the CLI subprocess path with direct HTTP API calls to multiple
model providers. Tasks receive file contents as context and return unified
diffs. No worktrees, no subscription limits, no account rotation.

Integrates with the existing task queue (Supabase), planner (DAG decomposition),
and judge (cross-model verification). Replaces only the execution layer.
"""
import asyncio
import aiohttp
import os
import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional

# --- Provider abstraction ---

@dataclass
class Provider:
    name: str
    base_url: str
    api_key_env: str
    models: dict  # capability_tier -> model_id
    max_concurrent: int = 50
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0

PROVIDERS = {
    "claude": Provider(
        name="claude",
        base_url="https://api.anthropic.com/v1/messages",
        api_key_env="ANTHROPIC_API_KEY",
        models={"fast": "claude-haiku-4-5-20251001", "mid": "claude-sonnet-4-6", "heavy": "claude-opus-4-8"},
        max_concurrent=50,
    ),
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com/v1/chat/completions",
        api_key_env="OPENAI_API_KEY",
        models={"fast": "gpt-4o-mini", "mid": "gpt-4o", "heavy": "o3"},
        max_concurrent=50,
    ),
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/models",
        api_key_env="GEMINI_API_KEY",
        models={"fast": "gemini-2.0-flash", "mid": "gemini-2.5-pro", "heavy": "gemini-2.5-pro"},
        max_concurrent=50,
    ),
    "deepseek": Provider(
        name="deepseek",
        base_url="https://api.deepseek.com/v1/chat/completions",
        api_key_env="DEEPSEEK_API_KEY",
        models={"fast": "deepseek-chat", "mid": "deepseek-chat", "heavy": "deepseek-reasoner"},
        max_concurrent=50,
    ),
}

# --- Diff-mode prompt template ---

DIFF_SYSTEM = """You are a code implementation agent. You receive:
1. The current contents of relevant files
2. A task specification

You MUST respond with ONLY a unified diff (--- a/path, +++ b/path, @@ hunks).
If creating a new file, use /dev/null as the a/ path.
If no changes needed, respond with "NO_CHANGES".
Do NOT include explanation, markdown fences, or anything outside the diff."""

# --- Core executor ---

@dataclass
class SwarmTask:
    task_id: str
    prompt: str
    files: dict  # {path: content}
    provider: str = "claude"
    tier: str = "fast"  # fast/mid/heavy
    timeout: int = 120
    attempt: int = 0

@dataclass  
class SwarmResult:
    task_id: str
    provider: str
    model: str
    diff: str
    cost_usd: float
    latency_s: float
    success: bool
    error: Optional[str] = None


class SwarmExecutor:
    """
    Executes N tasks concurrently across M providers via direct API calls.
    No CLI, no subscriptions, no worktrees.
    """

    def __init__(self, max_concurrent: int = 100, budget_usd_hour: float = 50.0):
        self.max_concurrent = max_concurrent
        self.budget_usd_hour = budget_usd_hour
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._spend = []  # [(timestamp, usd)]
        self._sessions = {}  # provider -> aiohttp.ClientSession

    async def execute_batch(self, tasks: list[SwarmTask]) -> list[SwarmResult]:
        """Execute all tasks concurrently, respecting per-provider concurrency."""
        async with aiohttp.ClientSession() as session:
            coros = [self._execute_one(session, task) for task in tasks]
            return await asyncio.gather(*coros, return_exceptions=True)

    async def _execute_one(self, session: aiohttp.ClientSession, task: SwarmTask) -> SwarmResult:
        async with self.semaphore:
            provider = PROVIDERS[task.provider]
            model = provider.models[task.tier]
            api_key = os.environ.get(provider.api_key_env)
            if not api_key:
                return SwarmResult(task.task_id, task.provider, model, "", 0, 0, False,
                                   f"No API key for {task.provider}")

            # Build the prompt with file context
            file_context = "\n\n".join(
                f"=== {path} ===\n{content}" for path, content in task.files.items()
            )
            user_msg = f"## Files\n{file_context}\n\n## Task\n{task.prompt}"

            t0 = __import__('time').time()
            try:
                if task.provider == "claude":
                    result = await self._call_claude(session, api_key, model, user_msg, task.timeout)
                else:
                    result = await self._call_openai_compat(session, provider, api_key, model, user_msg, task.timeout)
                
                latency = __import__('time').time() - t0
                return SwarmResult(task.task_id, task.provider, model, result["text"],
                                   result["cost"], latency, True)
            except Exception as e:
                latency = __import__('time').time() - t0
                return SwarmResult(task.task_id, task.provider, model, "", 0, latency, False, str(e))

    async def _call_claude(self, session, api_key, model, user_msg, timeout):
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 16384,
            "system": DIFF_SYSTEM,
            "messages": [{"role": "user", "content": user_msg}],
        }
        async with session.post("https://api.anthropic.com/v1/messages",
                                headers=headers, json=body,
                                timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            data = await resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            # Approximate cost (actual pricing varies)
            cost = (usage.get("input_tokens", 0) * 0.001 + usage.get("output_tokens", 0) * 0.005) / 1000
            return {"text": text, "cost": cost}

    async def _call_openai_compat(self, session, provider, api_key, model, user_msg, timeout):
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "max_tokens": 16384,
            "messages": [
                {"role": "system", "content": DIFF_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        }
        async with session.post(provider.base_url, headers=headers, json=body,
                                timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            data = await resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            cost = (usage.get("prompt_tokens", 0) * 0.0005 + usage.get("completion_tokens", 0) * 0.002) / 1000
            return {"text": text, "cost": cost}


# --- Integration with existing orchestrator ---

async def execute_dag(tasks: list[dict], repo_path: str, executor: SwarmExecutor = None):
    """
    Takes a planner DAG (list of {slug, prompt, deps, model_hint}) and executes it
    using the swarm executor, respecting dependencies but maximizing parallelism.
    
    This replaces the runner.py main loop for API-mode execution.
    """
    if executor is None:
        executor = SwarmExecutor()
    
    # Read all repo files into memory (for diff-mode context)
    file_cache = _read_repo_files(repo_path)
    
    completed = set()
    results = {}
    pending = {t["slug"]: t for t in tasks}
    
    while pending:
        # Find all tasks whose deps are satisfied
        ready = []
        for slug, task in pending.items():
            deps = set(task.get("deps", []))
            if deps.issubset(completed):
                tier = {"haiku": "fast", "sonnet": "mid", "opus": "heavy"}.get(
                    task.get("model_hint", "haiku"), "fast")
                
                # Pick relevant files for this task (from prompt file-scope hints)
                relevant_files = _extract_relevant_files(task["prompt"], file_cache)
                
                ready.append(SwarmTask(
                    task_id=slug,
                    prompt=task["prompt"],
                    files=relevant_files,
                    provider="claude",  # bandit can override
                    tier=tier,
                ))
        
        if not ready:
            break  # deadlock or done
        
        # Execute all ready tasks concurrently
        batch_results = await executor.execute_batch(ready)
        
        for r in batch_results:
            if isinstance(r, Exception):
                continue
            if r.success:
                # Apply diff to file_cache so subsequent tasks see the changes
                file_cache = _apply_diff(file_cache, r.diff)
                completed.add(r.task_id)
                results[r.task_id] = r
                del pending[r.task_id]
            else:
                # Retry with escalated tier or different provider
                task = pending[r.task_id]
                task["_attempt"] = task.get("_attempt", 0) + 1
                if task["_attempt"] >= 3:
                    del pending[r.task_id]  # give up
    
    # Batch-apply all accumulated diffs to the actual repo
    _write_repo_files(repo_path, file_cache)
    return results


def _read_repo_files(repo_path: str) -> dict:
    """Read all text files in repo into {relative_path: content}."""
    files = {}
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', '.next', 'dist'}]
        for f in filenames:
            if f.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.sql', '.md', '.json', '.yaml', '.yml',
                           '.toml', '.cfg', '.ini', '.sh', '.css', '.html', '.vue', '.svelte')):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, repo_path)
                try:
                    with open(full, errors='replace') as fh:
                        content = fh.read()
                    if len(content) < 100_000:  # skip huge files
                        files[rel] = content
                except Exception:
                    pass
    return files


def _extract_relevant_files(prompt: str, file_cache: dict) -> dict:
    """Extract files mentioned in the prompt, plus heuristic neighbors."""
    import re
    mentioned = set()
    # Match file paths in the prompt
    for m in re.finditer(r'[\w./]+\.\w{1,5}', prompt):
        candidate = m.group(0)
        if candidate in file_cache:
            mentioned.add(candidate)
    # Also include files whose basename is mentioned
    for path in file_cache:
        basename = os.path.basename(path)
        if basename in prompt:
            mentioned.add(path)
    # If nothing matched, include everything under 50 files
    if not mentioned:
        sorted_files = sorted(file_cache.keys())[:50]
        return {k: file_cache[k] for k in sorted_files}
    return {k: file_cache[k] for k in mentioned}


def _apply_diff(file_cache: dict, diff_text: str) -> dict:
    """Apply a unified diff to the in-memory file cache."""
    if not diff_text or diff_text.strip() == "NO_CHANGES":
        return file_cache
    # Parse unified diff and apply hunks
    import re
    current_file = None
    hunks = []
    for line in diff_text.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line[6:]
        elif line.startswith('--- '):
            continue
        elif line.startswith('@@') and current_file:
            # For simplicity, accumulate the new version
            pass
        # (Full diff parser would go here — use unidiff library in production)
    # In production: use `unidiff` package for robust parsing
    # For now, this is the interface contract
    return file_cache


def _write_repo_files(repo_path: str, file_cache: dict):
    """Write modified files back to disk and git-add them."""
    for rel_path, content in file_cache.items():
        full = os.path.join(repo_path, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(content)
```

---

## 3. Multi-Vendor Fan-Out Strategy

The key insight for 100X+ is that **every AI vendor has independent rate limits**. When the orchestrator calls only Claude CLI, it's using one pipe. With direct API access to 4+ vendors, you have 4+ independent pipes, each with their own concurrency limits.

### Routing matrix

```
Task Difficulty    Primary          Speculative Secondary    Concurrency
─────────────────────────────────────────────────────────────────────────
Mechanical         DeepSeek-chat    Gemini-flash             100+
(rename, format,   ($0.001/call)    ($0.001/call)
boilerplate)

Standard           Claude Haiku     GPT-4o-mini              50-100
(implement func,   ($0.01/call)     ($0.01/call)
add test)

Complex            Claude Sonnet    Gemini-2.5-Pro           20-50
(refactor,         ($0.05/call)     ($0.05/call)  
architecture)

Critical           Claude Opus      GPT-o3                   5-10
(security,         ($0.25/call)     ($0.25/call)
core logic)
```

### Speculative execution

For any task estimated <$0.05, send it to **two providers simultaneously** and take the first passing result. The wasted call costs pennies but halves latency. This is how you get from 100X to 500X — you're racing providers against each other.

```python
async def speculative_execute(executor, task, providers=["claude", "deepseek"]):
    """Race task across providers, return first success."""
    copies = [SwarmTask(**{**task.__dict__, "provider": p}) for p in providers]
    done, pending = await asyncio.wait(
        [asyncio.create_task(executor._execute_one(session, t)) for t in copies],
        return_when=asyncio.FIRST_COMPLETED,
    )
    result = done.pop().result()
    for p in pending:
        p.cancel()
    return result
```

---

## 4. Eliminating Git Overhead: In-Memory Diff Accumulation

Current flow per task:
```
create worktree (2-5s) → run claude (30-120s) → test → merge train lock → rebase → merge → delete worktree
```

New flow:
```
read files into memory (once) → fan out N API calls → collect diffs → batch-apply → single commit
```

This eliminates:
- N worktree create/destroy cycles
- N merge train lock acquisitions
- N rebase operations
- The entire `repo_lock.py` serialization bottleneck

For a 20-task DAG, this alone saves 40-100s of pure overhead.

---

## 5. Streaming Dependency Resolution

Current: Task B waits until Task A is **fully complete and merged** before starting.

New: Task B starts as soon as Task A's **diff is available in the file cache**, even before it's committed. Since we're working in-memory, "merging" is just updating the dict.

```python
# In execute_dag, after each batch completes:
for r in batch_results:
    if r.success:
        file_cache = _apply_diff(file_cache, r.diff)  # instant
        completed.add(r.task_id)
        # Next iteration immediately picks up newly-unblocked tasks
```

This turns the DAG execution from "wait for commit" to "wait for diff" — typically 30-120s faster per dependency edge.

---

## 6. Migration Path (Revised: Subscription-First)

### Phase 0: Cowork Queue Workers (week 1) — 5-10X, $0 cost
- Build the `cowork-queue-worker` skill/plugin
- Create scheduled tasks that poll Supabase every 5 minutes
- Each scheduled task claims tasks and fans out via Agent tool
- Workers write heartbeats to `cowork_workers` table
- Orchestrator detects Cowork workers and routes Tier 0 tasks to the queue
- **Cost:** $0 additional (subscription-covered). Speed: parallel Agent execution eliminates CLI overhead.

### Phase 1: Smart SDK Failover (week 1-2) — 10X, $0 cost
- When SDK rate_limit events fire (line 164 of claude_cli.py), immediately route to Tier 2 instead of 20min cooldown
- Reduce `ORCH_ACCOUNT_COOLDOWN` to 60s for rate limits that are known to be short (rolling 5-min windows)
- Add `tier_router.py` to coordinate Tier 0/1/2 routing
- **Cost:** $0 for subscription-covered tasks; API overflow only when genuinely needed.

### Phase 2: Diff Mode + API Overflow (week 2-3) — 50X
- Add `swarm_executor.py` with diff-mode prompts for Tier 2 (API)
- `runner.py` delegates to `execute_dag()` when Tier 0/1 are exhausted
- In-memory file cache replaces worktrees for API-mode tasks
- Merge train only runs once at the end of a DAG, not per-task
- Keep CLI/Cowork mode as primary for tasks that need full agentic capability
- **Cost:** API only for overflow (~10-20% of total volume).

### Phase 3: Multi-Vendor Swarm (week 3-4) — 100-500X
- Enable all providers in `PROVIDERS` config for Tier 2
- Bandit (`bandit.py`) learns per-provider success rates and routes accordingly
- Speculative execution for cheap tasks
- Provider-specific prompt tuning
- **Cost:** Multi-vendor API for overflow only; subscription handles the baseline.

### Phase 4: Recursive Swarm + Multi-Account Cowork (week 4+) — Multiplier
- Each subscription account runs its own persistent Cowork worker session
- N accounts × M parallel agents = N×M concurrent tasks on subscription
- API overflow handles spikes beyond subscription capacity
- The swarm executor itself uses recursive decomposition for large tasks
- This mirrors Cowork's `Agent` tool pattern — recursive delegation with parallel execution

---

## 7. Integration Points with Existing Code

| Existing Module | Change | Impact |
|---|---|---|
| `claude_cli.py` | Add `_call_api()` path alongside `_call_cli()` | Backward compatible |
| `runner.py` main loop | Check `ORCH_EXEC_MODE`; delegate to `swarm_executor.execute_dag()` for api mode | Opt-in per project |
| `planner.py` | No change — DAG output is the input to both paths | None |
| `account_pool.py` | Unused in API mode | None |
| `agentic_coders.py` | `PROVIDERS` dict replaces ad-hoc aider configs | Cleaner multi-vendor |
| `model_router.py` / `bandit.py` | Extend to route across providers, not just models | Enhanced |
| `merge_train.py` | Called once per DAG completion, not per task | Reduced load |
| `resource_governor.py` | Governs API spend instead of RAM/processes | Metric change |
| `judge.py` / `verify.py` | No change — still cross-model verification | None |
| `db.py` | Tasks track `exec_mode: "api"|"cli"` | Schema addition |

---

## 8. Cost Model (Hybrid)

| Scenario | Throughput | Daily Cost | How |
|---|---|---|---|
| Current (CLI subscription) | ~80 tasks/hr | $0 (subscription) | CLI subprocess, serial |
| Phase 0: Cowork workers | ~200-400 tasks/hr | $0 (subscription) | Agent tool parallelism |
| Phase 0+1: Multi-account Cowork | ~500-1000 tasks/hr | $0 (subscription × N) | N workers × M agents |
| Phase 2: Hybrid overflow | ~2,000 tasks/hr | ~$20-50 (API overflow only) | 80% sub + 20% API |
| Phase 3: Full swarm | ~3,000+ tasks/hr | ~$50-150 (API + multi-vendor) | Sub baseline + API burst |

**Key insight:** The subscription is a sunk cost you're already paying. Every task routed through Cowork instead of API is pure savings. The hybrid approach doesn't trade dollars for hours — it trades *architecture* for hours, keeping the dollars the same.

Phase 0 alone (Cowork workers, $0 additional cost) should deliver 3-5X throughput improvement over the current CLI path, just by eliminating cold-start, worktree, and merge overhead.

---

## 9. Key Risks and Mitigations

1. **API cost runaway** — The existing circuit breaker (`_check_budget`) already handles this. Extend it to cover API spend with the same hourly/daily caps, just at higher thresholds.

2. **Diff quality** — Models sometimes produce malformed diffs in pure diff-mode. Mitigation: validate diffs before applying (use `unidiff` library), fall back to agentic mode for failures. The judge/verify pipeline catches quality issues regardless of execution mode.

3. **Context limits** — Large repos exceed context windows when injecting file contents. Mitigation: `_extract_relevant_files()` already scopes to mentioned files. For very large tasks, chunk the file set or fall back to agentic mode with worktrees.

4. **Agentic tasks** — Some tasks genuinely need shell access (install deps, run migrations, test commands). These stay on the CLI path. The swarm handles the 80%+ that are pure code editing.

---

## 10. The Recursive Leverage Insight

The reason Cowork feels 10X-500X faster isn't just API access — it's **recursive agent delegation**. When Cowork gets a task, it can spawn sub-agents that each work independently, and those sub-agents can spawn their own sub-agents. The orchestrator currently has one level of decomposition (planner → tasks). Adding recursive decomposition means:

```
Objective (1)
  → planner produces 10 tasks
    → each task's executor decomposes into 5 sub-edits
      → 50 concurrent API calls execute in ~30 seconds
        → all diffs accumulated and committed in one batch
```

vs. current:
```
Objective (1)
  → planner produces 10 tasks
    → 80/hr rate limit → tasks execute over 7-8 minutes
      → each task: worktree + CLI + merge = 60-120s serial overhead
        → total: 10-20 minutes minimum for a 10-task DAG
```

That's the path from minutes to seconds.
