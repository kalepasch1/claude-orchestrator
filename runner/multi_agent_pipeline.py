#!/usr/bin/env python3
"""
multi_agent_pipeline.py — Multi-agent pipelining (100X throughput improvement).

Instead of one expensive agent per task, decompose into a pipeline:

  scout (cheap)      → find relevant files, assess scope
  planner (mid)      → write implementation plan with specific diffs
  implementer (full) → execute the plan (focused, cheaper because pre-planned)
  verifier (cheap)   → review the output (different vendor for independence)

4 cheap calls instead of 1 expensive open-ended call. Each stage runs on the
cheapest capable model for that role.

Budget-aware sizing:
  - Small tasks (< $0.50 expected): 2-stage (scout+implement)
  - Medium tasks ($0.50-$2.00): 3-stage (scout+plan+implement)
  - Large tasks (> $2.00): 4-stage (scout+plan+implement+verify)
  - High-risk tasks: 4-stage always

Usage:
    import multi_agent_pipeline
    result = multi_agent_pipeline.should_pipeline(task)
    if result["pipeline"]:
        stages = multi_agent_pipeline.build_pipeline(task, project, repo)
"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PIPELINE_MIN_COMPLEXITY = float(os.environ.get("ORCH_PIPELINE_MIN_COMPLEXITY", "0.5"))
SCOUT_TIMEOUT = int(os.environ.get("ORCH_SCOUT_TIMEOUT", "60"))
PLAN_TIMEOUT = int(os.environ.get("ORCH_PLAN_TIMEOUT", "90"))

SCOUT_PROMPT = """You are a code scout. Your ONLY job is to identify the files and functions
relevant to this task. Do NOT write code. Do NOT implement anything.

TASK: {task_prompt}
PROJECT: {project}

Search the codebase and return JSON:
{{"relevant_files": ["path/to/file1.ts", "path/to/file2.py"],
  "entry_points": ["functionName", "ClassName.method"],
  "dependencies": ["file that imports from the changed files"],
  "complexity": "low|medium|high",
  "estimated_changes": N}}"""

PLAN_PROMPT = """You are a code planner. Given the scout's file analysis, write a precise
implementation plan. Do NOT write code. Describe what to change in each file.

TASK: {task_prompt}
SCOUT FINDINGS: {scout_result}

Return JSON:
{{"steps": [
    {{"file": "path/to/file.ts", "action": "modify|create|delete",
      "description": "what to change and why", "estimated_lines": N}}
  ],
  "test_strategy": "what tests to add/modify",
  "risks": ["risk1"],
  "total_estimated_lines": N}}"""


def should_pipeline(task, diff_plan=None):
    """Determine if a task should use multi-agent pipelining.

    Returns: {pipeline: bool, stages: int, reason: str}
    """
    prompt = task.get("prompt", "")
    kind = task.get("kind", "")

    # Never pipeline recovery/mechanical tasks — they're too small
    if kind in ("recovery", "mechanical", "config"):
        return {"pipeline": False, "stages": 1, "reason": "too small for pipeline"}

    # Estimate complexity
    prompt_len = len(prompt)
    is_complex = prompt_len > 500 or kind in ("feature", "refactor", "security")

    # Check if diff_compiler found templates (if so, pipeline adds less value)
    has_template = diff_plan and diff_plan.get("has_plan") and diff_plan.get("confidence", 0) > 0.7
    if has_template:
        return {"pipeline": False, "stages": 1, "reason": "strong template match — pipeline unnecessary"}

    if not is_complex:
        return {"pipeline": False, "stages": 1, "reason": "simple task"}

    # Determine stage count based on expected cost
    try:
        import model_portfolios
        domain = model_portfolios.classify(task, [])
        # High-risk domains always get full pipeline
        if domain in ("security", "data"):
            return {"pipeline": True, "stages": 4, "reason": f"high-risk domain ({domain})"}
    except Exception:
        pass

    if prompt_len > 2000:
        return {"pipeline": True, "stages": 4, "reason": "large complex task"}
    elif prompt_len > 500:
        return {"pipeline": True, "stages": 3, "reason": "medium complexity"}
    else:
        return {"pipeline": True, "stages": 2, "reason": "moderate task"}


def run_scout(task, project, repo):
    """Run the scout stage: identify relevant files.

    Returns: scout result dict or None
    """
    try:
        import model_gateway, model_policy
        task_prompt = (task.get("prompt") or "")[:1500]
        prompt = SCOUT_PROMPT.format(task_prompt=task_prompt, project=project)

        # Use cheapest model for scouting
        prov, model, _ = model_policy.choose("review", agentic=False, need=4)

        res = model_gateway.complete(prov, model, prompt, project=project,
                                     timeout=SCOUT_TIMEOUT, operation="pipeline_scout",
                                     task_class="review")
        text = res.get("text", "")
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            result = json.loads(m.group(0))
            result["model"] = f"{prov}:{model}"
            result["cost_usd"] = res.get("cost_usd", 0)
            return result
    except Exception:
        pass
    return None


def run_planner(task, project, scout_result):
    """Run the planner stage: create implementation plan from scout findings.

    Returns: plan result dict or None
    """
    try:
        import model_gateway, model_policy
        task_prompt = (task.get("prompt") or "")[:1500]
        scout_json = json.dumps(scout_result, default=str)[:1000]
        prompt = PLAN_PROMPT.format(task_prompt=task_prompt, scout_result=scout_json)

        # Use mid-tier model for planning
        prov, model, _ = model_policy.choose("review", agentic=False, need=3)

        res = model_gateway.complete(prov, model, prompt, project=project,
                                     timeout=PLAN_TIMEOUT, operation="pipeline_plan",
                                     task_class="review")
        text = res.get("text", "")
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            result = json.loads(m.group(0))
            result["model"] = f"{prov}:{model}"
            result["cost_usd"] = res.get("cost_usd", 0)
            return result
    except Exception:
        pass
    return None


def build_enriched_prompt(task, scout_result=None, plan_result=None):
    """Build an enriched implementation prompt from pipeline stages.

    The implementer gets a pre-digested, focused prompt instead of open-ended exploration.
    """
    original = task.get("prompt", "")
    enriched = ""

    if scout_result:
        files = scout_result.get("relevant_files", [])
        entries = scout_result.get("entry_points", [])
        complexity = scout_result.get("complexity", "unknown")

        enriched += "## SCOUT ANALYSIS\n"
        if files:
            enriched += f"Relevant files: {', '.join(files[:10])}\n"
        if entries:
            enriched += f"Entry points: {', '.join(entries[:5])}\n"
        enriched += f"Complexity: {complexity}\n\n"

    if plan_result:
        steps = plan_result.get("steps", [])
        enriched += "## IMPLEMENTATION PLAN\n"
        for i, step in enumerate(steps[:10]):
            enriched += f"{i+1}. {step.get('action', 'modify')} `{step.get('file', '')}`: {step.get('description', '')}\n"
        test_strategy = plan_result.get("test_strategy", "")
        if test_strategy:
            enriched += f"\nTest strategy: {test_strategy}\n"
        risks = plan_result.get("risks", [])
        if risks:
            enriched += f"Risks: {'; '.join(risks[:3])}\n"
        enriched += "\n"

    if enriched:
        return enriched + "## TASK\n" + original
    return original


def pipeline_cost(scout_result=None, plan_result=None):
    """Total cost of pipeline stages so far."""
    cost = 0
    if scout_result:
        cost += scout_result.get("cost_usd", 0)
    if plan_result:
        cost += plan_result.get("cost_usd", 0)
    return cost
