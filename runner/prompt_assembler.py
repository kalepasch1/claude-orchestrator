#!/usr/bin/env python3
"""
prompt_assembler.py - the ONE composition point for every prompt sent to any coder
(Claude Code via claude_cli.py, aider/DeepSeek/Gemini/GPT via agentic_coders.py).

Before this module, runner.run_task() hand-concatenated seven separately-imported layers
inline (prefix + focus + blast + reuse + regression.inject(kb.inject(contracted)) +
feedback.INSTRUCTION + REUSE_FIRST) — the only such call site, but nothing enforced that any
OTHER caller building a prompt (a periodic job, a future coder integration) would compose the
same layers in the same order, and nothing measured what the composed prompt actually cost in
tokens. assemble() is that enforcement point now; runner.py's run_task() calls it instead of
concatenating by hand.

Layer order (each best-effort — a missing/erroring module just contributes nothing, never
raises):
  1. distilled task template   (prompt_distillation.find_distilled/apply_distilled) - if a
     similar task has a proven minimal template, start from that instead of the full body.
  2. stable cached prefix      (caching.load_prefix) - CLAUDE.md/CONVENTIONS.md, byte-identical
     across tasks in a repo so Claude Code's automatic prompt caching hits.
  3. distilled per-project brief (_project_brief, <=4KB) - a few recent CLAUDE.md convention
     bullets + a one-line recent-outcomes signal. Note: the mission spec that requested this
     layer named prompt_distillation.py as its home, but that module already does something
     different (per-task template distillation, not a per-project brief) — extending it to also
     mean "project brief" would have overloaded one name with two concepts, so this small
     brief lives here instead, right next to the thing that assembles it.
  4. scoped file focus / blast radius / cross-project capability reuse notes
  5. pipeline_contract wrap (routing/QA metadata)
  6. knowledge_embed + regression injection (top-k prior solutions, do/avoid rules)
  7. reuse-first instruction tail
  8. final char cap (_cap) so the whole thing stays under the model's practical context budget

assemble() returns {"prompt", "token_estimate", "layers"} — layers lists which stages actually
contributed, and token_estimate (len//4, a standard rough estimate) gets logged so per-task
input-token cost is visible over time instead of only discoverable by reading provider bills.
"""
import os, sys, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_AGENT_PROMPT_CHARS = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))
BRIEF_MAX_BYTES = int(os.environ.get("ORCH_BRIEF_MAX_BYTES", "4096"))

REUSE_FIRST = ("\n\n## Reuse before you draft (cost discipline)\n"
    "Before writing net-new code: (1) search THIS repo for an existing helper/component/pattern "
    "and extend it; (2) check the injected prior-solution notes above and the shared kernel "
    "(packages/darwin-kernel / vendor/darwin-kernel) for something to import or adapt; (3) if the "
    "same need clearly exists in sibling apps, write it as a small reusable module and note "
    "'CANDIDATE-SHARED: <what>' in your final message so it can be promoted to a shared capability "
    "instead of re-drafted per app. Prefer the smallest diff that reuses existing code.")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
ASSEMBLY_LOG = os.path.join(HOME, "prompt_assembly.jsonl")


def _cap(prompt):
    """Keep agent requests comfortably below context limits after tool/system overhead."""
    text = prompt or ""
    if len(text) <= MAX_AGENT_PROMPT_CHARS:
        return text
    head = min(20000, MAX_AGENT_PROMPT_CHARS // 3)
    tail = MAX_AGENT_PROMPT_CHARS - head
    return (
        text[:head].rstrip() +
        "\n\n[ORCHESTRATOR COMPACTION: middle context removed to stay below model limits. "
        "Use the focus files, task contract, and final request below; inspect repo files directly "
        "instead of relying on omitted transcript bulk.]\n\n" +
        text[-tail:].lstrip()
    )


def _project_brief(project, repo):
    """A few recent CLAUDE.md convention bullets + a one-line outcomes signal, capped at
    BRIEF_MAX_BYTES. Deliberately NOT cached to disk (unlike the fuller caching.load_prefix
    prefix) — this is already a small, cheap file read plus one bounded DB query, and caching
    it introduces staleness risk for no real savings. Never raises; returns '' on any failure."""
    if not project or not repo:
        return ""
    bullets = []
    try:
        text = open(os.path.join(repo, "CLAUDE.md"), encoding="utf-8", errors="replace").read()
        bullets = [b.strip() for b in re.findall(r"^\s*[-*]\s+.+$", text, re.M)[-8:]]
    except Exception:
        pass
    signal = ""
    try:
        import db
        rows = db.select("outcomes", {"select": "tests_passed,integrated",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "10"}) or []
        if rows:
            merged = sum(1 for r in rows if r.get("integrated"))
            passed = sum(1 for r in rows if r.get("tests_passed"))
            signal = f"recent signal: {merged}/{len(rows)} merged, {passed}/{len(rows)} tests passed"
    except Exception:
        pass
    if not bullets and not signal:
        return ""
    lines = [f"# {project} — project brief (auto)"]
    if bullets:
        lines.append("## Key conventions")
        lines.extend(bullets)
    if signal:
        lines.append(f"## {signal}")
    brief = "\n".join(lines).strip() + "\n\n"
    if len(brief.encode("utf-8")) > BRIEF_MAX_BYTES:
        brief = brief.encode("utf-8")[:BRIEF_MAX_BYTES].decode("utf-8", errors="ignore")
    return brief


def _distilled_body(task_body, task, project):
    try:
        import prompt_distillation
        d = prompt_distillation.find_distilled(task, current_project=project)
        if d:
            return prompt_distillation.apply_distilled(task_body, d), True
    except Exception:
        pass
    return task_body, False


def _log_assembly(project, slug, token_estimate, layers):
    try:
        os.makedirs(os.path.dirname(ASSEMBLY_LOG), exist_ok=True)
        with open(ASSEMBLY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "project": project, "slug": slug,
                                "token_estimate": token_estimate, "layers": layers}) + "\n")
    except Exception:
        pass


def assemble(task_body, *, project="", repo="", kind="build", source="unknown", slug="",
             material=False, task=None, use_retrieval=True):
    """Compose the full prompt sent to a coder. `task` (a dict with at least 'prompt'/'kind')
    is optional — pass it when available so the distilled-template lookup can match on it;
    without it, this falls back to a task dict built from the other args."""
    layers = []
    t = task or {"prompt": task_body, "kind": kind, "slug": slug}

    body, used_distilled = _distilled_body(task_body, t, project)
    if used_distilled:
        layers.append("distilled_template")

    prefix = ""
    try:
        import caching
        prefix = caching.load_prefix(repo)
        if prefix:
            layers.append("cached_prefix")
    except Exception:
        pass

    brief = _project_brief(project, repo)
    if brief:
        layers.append("project_brief")

    focus = blast = reuse = ""
    if use_retrieval:
        try:
            import context_retrieval
            focus = context_retrieval.focus_note(repo, body) or ""
            if focus:
                layers.append("focus")
        except Exception:
            pass
        try:
            import blast_radius
            blast = blast_radius.note_for_task(repo, body) or ""
            if blast:
                layers.append("blast_radius")
        except Exception:
            pass
    try:
        import capability
        reuse = capability.reuse_note(body, project=project) or ""
        if reuse:
            layers.append("capability_reuse")
    except Exception:
        pass

    contracted = body
    try:
        import pipeline_contract
        contracted = pipeline_contract.wrap_prompt(body, project=project, kind=kind,
                                                    source=source, slug=slug, material=material)
        if contracted != body:
            layers.append("pipeline_contract")
    except Exception:
        pass

    injected = contracted
    try:
        import knowledge_embed
        after_kb = knowledge_embed.inject(injected)
        if after_kb != injected:
            layers.append("knowledge_inject")
        injected = after_kb
    except Exception:
        pass
    try:
        import regression
        after_reg = regression.inject(injected)
        if after_reg != injected:
            layers.append("regression_inject")
        injected = after_reg
    except Exception:
        pass

    tail = ""
    try:
        import feedback
        tail += feedback.INSTRUCTION or ""
        if feedback.INSTRUCTION:
            layers.append("feedback_instruction")
    except Exception:
        pass

    prompt = prefix + brief + focus + blast + reuse + injected + tail + REUSE_FIRST
    prompt = _cap(prompt)
    token_estimate = len(prompt) // 4
    _log_assembly(project, slug, token_estimate, layers)
    return {"prompt": prompt, "token_estimate": token_estimate, "layers": layers}


def stats(limit=200):
    """Average/last-N token estimates from the assembly log — cheap operator visibility into
    whether prompt size is trending up or down."""
    try:
        with open(ASSEMBLY_LOG) as f:
            rows = [json.loads(l) for l in f if l.strip()][-limit:]
    except FileNotFoundError:
        return {"count": 0, "avg_tokens": 0}
    except Exception:
        return {"count": 0, "avg_tokens": 0, "error": "corrupt log"}
    if not rows:
        return {"count": 0, "avg_tokens": 0}
    avg = sum(r.get("token_estimate", 0) for r in rows) / len(rows)
    return {"count": len(rows), "avg_tokens": round(avg)}


def invalidate():
    try:
        os.remove(ASSEMBLY_LOG)
    except FileNotFoundError:
        pass
    except Exception:
        pass


if __name__ == "__main__":
    print(json.dumps(assemble("Improve the dashboard queue flow.", project="beethoven",
                              repo=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     indent=2)[:2000])
