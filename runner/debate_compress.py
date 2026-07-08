#!/usr/bin/env python3
"""
debate_compress.py — Multi-agent debate compression (80% cost reduction).

Instead of N separate model calls for N debate participants, compress the entire
debate into a SINGLE model call where one model role-plays all participants:

  "You are mediating a debate. Play these roles in sequence:
   1. PROPOSER: describe your approach
   2. CRITIC: attack the weakest points
   3. REUSER: find prior diffs/templates to adapt
   4. MINIMIZER: reduce scope and cost

   Return the consensus as a structured plan."

This preserves the adversarial quality of the debate (the model genuinely finds
weaknesses when prompted to attack) while eliminating N-1 model calls.

Usage:
    import debate_compress
    result = debate_compress.compressed_debate(task, assignment, project)
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEBATE_PROMPT = """You are moderating a pre-implementation debate for a coding task.
Play each role IN SEQUENCE — genuinely adopt each perspective, don't just agree.

## TASK
{task_prompt}

## TASK CLASS: {task_class}
## ESTIMATED COST: ${est_cost:.3f} | CONFIDENCE: {confidence:.0%}

---
**ROLE 1 — PROPOSER** (the implementer):
Describe the simplest correct approach in <=3 sentences. Name exact files to change.

**ROLE 2 — CRITIC** (the adversary):
Attack the proposal. What will break? What edge case is missed? What's the biggest risk?
Be specific — name the line of code or the test case.

**ROLE 3 — REUSER** (the archaeologist):
What prior merged diffs, templates, or patterns from this project could be adapted?
What existing code does 80% of what's needed? Name specific files/functions.

**ROLE 4 — MINIMIZER** (the cost optimizer):
How can this be done with FEWER file changes, FEWER lines, LESS context needed?
What can be deferred to a follow-up task? What's the absolute minimum viable change?

---
Now SYNTHESIZE all four perspectives into a consensus plan.

Return JSON:
{{"approach": "the agreed approach (<=3 sentences)",
  "files": ["file1.py", "file2.ts"],
  "risks": ["risk1", "risk2"],
  "reuse_hints": ["file_or_pattern_to_adapt"],
  "scope_reduction": "what was cut to minimize cost",
  "estimated_lines": 0,
  "confidence_after_debate": 0.0}}"""


def compressed_debate(task, assignment=None, project=None):
    """Run a compressed 4-role debate in a single model call.

    Returns: debate result dict or None on failure.
    """
    try:
        import model_gateway, model_policy

        task_prompt = (task.get("prompt") or "")[:2000]
        task_class = (assignment or {}).get("task_class", "feature")
        est_cost = (assignment or {}).get("implementer", {}).get("est_cost", 0.50)
        confidence = (assignment or {}).get("implementer", {}).get("confidence", 0.5)

        prompt = DEBATE_PROMPT.format(
            task_prompt=task_prompt,
            task_class=task_class,
            est_cost=est_cost,
            confidence=confidence,
        )

        # Use the cheapest capable model for the debate
        prov, model, _ = model_policy.choose("review", agentic=False, need=4)

        res = model_gateway.complete(prov, model, prompt, project=project,
                                     timeout=90, operation="debate_compress",
                                     task_class="review")
        text = res.get("text", "")
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            result = json.loads(m.group(0))
            result["model"] = f"{res.get('provider')}:{res.get('model')}"
            result["cost_usd"] = res.get("cost_usd", 0)
            result["compressed"] = True
            return result

    except Exception as e:
        pass

    return None


def inject_debate(prompt, debate_result):
    """Inject debate consensus into the agent prompt."""
    if not debate_result:
        return prompt

    injection = "\n\n## PRE-IMPLEMENTATION DEBATE CONSENSUS\n"
    injection += f"Approach: {debate_result.get('approach', '')}\n"

    files = debate_result.get("files", [])
    if files:
        injection += f"Focus files: {', '.join(files[:10])}\n"

    risks = debate_result.get("risks", [])
    if risks:
        injection += f"Risks to mitigate: {'; '.join(risks[:3])}\n"

    reuse = debate_result.get("reuse_hints", [])
    if reuse:
        injection += f"Reuse/adapt: {', '.join(reuse[:5])}\n"

    scope = debate_result.get("scope_reduction", "")
    if scope:
        injection += f"Scope reduction: {scope}\n"

    return injection + "\n" + prompt
