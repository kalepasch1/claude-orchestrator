#!/usr/bin/env python3
"""
planner.py - plan-then-fan-out. Turns ONE giant master prompt into a DAG of small,
scoped tasks with dependencies, so the orchestrator runs independent work in
parallel and avoids the 150k-650k-token compaction spirals you were hitting.

    python3 app/planner.py "Build the non-custodial settlement engine: ...long prompt..." > tasks.yaml

How: asks a model to decompose the prompt into JSON tasks, each with an explicit
file scope and acceptance test, plus `deps` (slugs that must finish first).
Independent tasks share no files -> safe to run concurrently. Dependent tasks are
ordered. Falls back to a single task if planning fails. Mockable via CLAUDE_BIN.

TDD-first enforcement: when a task kind matches ORCH_TDD_REQUIRED_KINDS, planner
automatically inserts a 'write_tests' phase BEFORE the 'implement' phase. This ensures
tests are written with explicit acceptance criteria before any implementation begins.
"""
import os, sys, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli
import tdd_gate
import tests_first_gate
import design_sources

PLAN_MODEL = os.environ.get("PLAN_MODEL", "claude-opus-4-8")

META = """You are a build planner. Decompose the REQUEST below into the smallest set of
independently-shippable tasks. Output ONLY a JSON array. Each item:
{"slug":"kebab-case","prompt":"a SELF-CONTAINED instruction incl. an explicit file
scope and an acceptance test to run","deps":["slugs that must complete first"],
"model_hint":"haiku|sonnet|opus"}
Model hint guide: use "haiku" for self-contained Python/TS implementation with a defined
interface and <800 estimated output lines; use "sonnet" when output likely exceeds 800 lines
OR the task requires cross-file reasoning/ambiguous requirements; reserve "opus" for
open-ended architecture or tasks with no clear acceptance criteria.
Rules: tasks that touch DIFFERENT files must NOT list each other in deps (so they run
in parallel). Tasks editing the SAME files MUST be chained via deps to prevent merge
conflicts. Keep each prompt small enough to avoid context compaction.
MAXIMIZE PARALLELISM / MINIMIZE DEPTH: produce a WIDE, SHALLOW graph. After the single
"contracts" task, put as many INDEPENDENT sibling tasks as possible at depth 1 (deps just
["contracts"]) so the fleet runs them all at once. Do NOT create long chains A->B->C->D unless
each step genuinely edits the previous step's files; a task should depend ONLY on the minimal set
it truly needs (never add a dep "just to be safe" — that serializes the graph and starves
throughput). Target max dependency depth <= 2 beyond contracts.
CONTRACT-FIRST (required): the FIRST task MUST have slug "contracts" and deps []; it
defines the shared interfaces/types/API signatures/DB schema that the others build
against (and ONLY those - no implementation). EVERY other task MUST list "contracts"
in its deps. This lets parallel branches agree on boundaries up front so they cannot
structurally conflict at merge time.
REQUEST:
"""


def _apply_tdd_gating(tasks):
    """
    Apply TDD-first enforcement to tasks. For each task whose kind is gated for TDD:
    - Insert a 'write_tests' phase BEFORE the 'implement' phase in its DAG deps
    - The write_tests task has the same deps as the original task
    - The original task then depends on write_tests completing
    - Acceptance criteria (metrics, edge_cases, must_pass_tests) are extracted from task prompt

    This is a no-op if ORCH_TDD_REQUIRED_KINDS is empty.
    """
    try:
        gated_kinds = tdd_gate.get_required_kinds()
    except Exception:
        return tasks
    if not gated_kinds:
        return tasks

    modified = []
    test_tasks = {}

    for t in tasks:
        slug = t.get("slug", "")
        is_gated = tdd_gate.is_tdd_gated(slug)

        if is_gated and slug != "contracts":
            test_slug = f"{slug}-write-tests"
            if test_slug not in test_tasks:
                write_prompt = (
                    f"Write failing tests + acceptance criteria for '{slug}':\n\n"
                    f"{t.get('prompt', '')[:500]}\n\n"
                    f"Task:\n"
                    f"1. Read the original prompt above to understand acceptance criteria.\n"
                    f"2. Write comprehensive failing tests to tests/test_{slug}.py.\n"
                    f"3. Each test docstring MUST include '[ACCEPTANCE CRITERION]:' followed by the requirement.\n"
                    f"4. Output a JSON block with acceptance_criteria:\n"
                    f'{{"acceptance_criteria": {{\n'
                    f'  "metrics": {{"latency_ms": "<100", "coverage_%": ">=90"}},\n'
                    f'  "edge_cases": ["case1", "case2"],\n'
                    f'  "must_pass_tests": ["test_main", "test_edge_cases"]\n'
                    f'}}}}\n'
                    f"5. All tests MUST fail before implementation.\n"
                    f"6. Do NOT implement anything yet — only tests + criteria."
                )
                test_task = {
                    "slug": test_slug,
                    "prompt": write_prompt,
                    "deps": t.get("deps", []),
                    "model_hint": "haiku",
                }
                modified.append(test_task)
                test_tasks[test_slug] = True

            t_copy = dict(t)
            original_deps = t_copy.get("deps", [])
            t_copy["deps"] = list(set(original_deps + [test_slug]))
            t_copy["acceptance_criteria"] = {
                "metrics": {},
                "edge_cases": [],
                "must_pass_tests": []
            }
            # Contract-first proof rewriting: the code task's proof becomes
            # "that acceptance test passes + suite green"
            try:
                import pipeline_contract
                t_copy["proof"] = pipeline_contract.rewrite_proof_for_contract_first(
                    t_copy.get("proof", ""), test_slug)
            except Exception:
                t_copy["proof"] = f"acceptance test from '{test_slug}' passes + suite green"
            modified.append(t_copy)
        else:
            modified.append(t)

    return modified


def _shard_by_sections(master: str) -> list:
    """Deterministic, model-free fallback: split a large multi-section freeform prompt into a
    contract-first DAG by its section headings (## / ### / '1.' / '2)' style). Guarantees that a
    failed or timed-out LLM plan never collapses a huge prompt into one monolithic, unexecutable
    master-task. Returns [] if the prompt cannot be meaningfully sharded (caller keeps 1 task)."""
    lines = master.splitlines()
    header_re = re.compile(r'^\s*(?:#{2,4}\s+|\d+[.)]\s+)(.+)$')
    sections = []            # list of (title|None, [lines])
    cur_title, cur_body = None, []
    for ln in lines:
        m = header_re.match(ln)
        if m and len(m.group(1).strip()) >= 3:
            if cur_title is not None or cur_body:
                sections.append((cur_title, cur_body))
            cur_title, cur_body = m.group(1).strip(), [ln]
        else:
            cur_body.append(ln)
    if cur_title is not None or cur_body:
        sections.append((cur_title, cur_body))

    real = [(t, b) for (t, b) in sections if t and len("\n".join(b).strip()) > 40]
    if len(real) < 2:
        return []

    preamble = ""
    if sections and sections[0][0] is None:
        preamble = "\n".join(sections[0][1]).strip()

    def _slug(t):
        s = re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')
        return (s[:48].rstrip('-') or "section")

    tasks = [{
        "slug": "contracts",
        "prompt": ("Establish the SHARED contracts/types/interfaces/DB-migration stubs that the "
                   "sibling work items below depend on, and nothing else. Overall context:\n\n"
                   + preamble +
                   "\n\nDeliver only the shared interfaces + a short README describing them; the "
                   "sibling tasks implement against these contracts."),
        "deps": [], "model_hint": "opus",
    }]
    seen = {"contracts"}
    for (title, body) in real:
        base = _slug(title)
        slug, i = base, 2
        while slug in seen:
            slug, i = f"{base}-{i}", i + 1
        seen.add(slug)
        body_txt = "\n".join(body).strip()
        tasks.append({
            "slug": slug,
            "prompt": (preamble + "\n\n---\nImplement ONLY this section, end to end — wire it, "
                       "test it, no dead code, honor the shared contracts:\n\n" + body_txt),
            "deps": ["contracts"],
            "model_hint": "opus" if len(body_txt) > 4000 else "sonnet",
        })
    return tasks


def _shard_coarse(master: str, max_tasks: int) -> list:
    """Group a prompt's sections into a SMALL number of coherent, contract-first tasks
    (<= max_tasks). Used by the fast_coherent / governed_heavy lanes: fewer, larger tasks
    keep context and cut merge-train hops vs. the full per-section shard, while still giving
    the pipeline verifiable units. Falls back to [] (caller keeps a single task) if it can't
    meaningfully group."""
    fine = _shard_by_sections(master)          # contract + one task per section, or []
    if not fine:
        return []
    contract, sections = fine[0], fine[1:]
    if max_tasks <= 1 or len(sections) <= max(1, max_tasks - 1):
        return fine                             # already small enough
    buckets = max(1, max_tasks - 1)             # reserve one slot for the contracts task
    groups = [[] for _ in range(buckets)]
    for i, t in enumerate(sections):
        groups[i % buckets].append(t)
    merged = [contract]
    for gi, g in enumerate(groups, 1):
        if not g:
            continue
        titles = " + ".join(s["slug"] for s in g)
        body = "\n\n".join(s["prompt"] for s in g)
        merged.append({
            "slug": f"group-{gi}",
            "prompt": ("Implement ALL of the following related sections together, coherently, "
                       "end to end (wire + test, no dead code, honor the shared contracts). "
                       f"Sections: {titles}\n\n{body}"),
            "deps": ["contracts"],
            "model_hint": "opus",
        })
    return merged


def plan(master: str, repo: str = None, project: str = None) -> list:
    spec = ""
    if repo:
        try:
            design = design_sources.contract(repo)
            if design["text"]:
                spec = "\n\n" + design["text"]
        except Exception as e:
            sys.stderr.write(f"[planner] design-source discovery failed ({e}); continuing\n")
        # OUTCOME-WEIGHTED PLANNING: fold in what ACTUALLY merged before (conventions distilled by
        # learn_from_merges into CLAUDE.md) so the decomposition mirrors past first-pass successes.
        cmd_path = os.path.join(repo, "CLAUDE.md")
        if os.path.isfile(cmd_path):
            try:
                with open(cmd_path) as _f:
                    txt = _f.read()
                marker = "## Learned from merged work"
                if marker in txt:
                    lesson = txt[txt.index(marker):][:3000]
                    spec += (f"\n\n# What has merged cleanly here before (bias the plan toward these "
                             f"patterns to maximize first-pass merge rate):\n{lesson}\n\n")
            except Exception:
                pass
    # ADAPTIVE WORKFLOW ROUTING (2026-07-28): pick the execution profile for this objective so the
    # fleet optimizes for the RIGHT thing (speed / throughput / safety / cost) instead of forcing
    # every objective through the heavy wide-shard + merge-train pipeline. Default profile
    # (parallel_fleet) reproduces historical behavior, so unclassified work is unchanged.
    try:
        import workflow_router
        prof = workflow_router.profile_for(master, project=project)
    except Exception as e:
        sys.stderr.write(f"[planner] workflow_router unavailable ({e}); using full-shard default\n")
        prof = None
    shard_mode = prof.shard if prof else "full"
    default_model = prof.model_hint if prof else None
    sys.stderr.write(f"[planner] workflow={getattr(prof,'mode','full')} shard={shard_mode} "
                     f"model={default_model} max_tasks={getattr(prof,'max_tasks','-')} "
                     f"({len(master)} chars, {getattr(prof,'rationale','')})\n")

    tasks = None
    if shard_mode == "none":
        # coherent single-body / trivial / research: one strong task, no shard.
        tasks = [{"slug": "task", "prompt": master, "deps": [], "model_hint": default_model or "opus"}]
    elif shard_mode == "light":
        # few coherent tasks — keep context, cut merge-train hops.
        tasks = _shard_coarse(master, (prof.max_tasks if prof else 4))
        if not tasks:
            tasks = [{"slug": "task", "prompt": master, "deps": [], "model_hint": default_model or "opus"}]

    if tasks is None:
        # full shard: the LLM planner (wide-shallow DAG), with the deterministic section-shard
        # as a robustness fallback so a big prompt never collapses to one master-task.
        try:
            r = claude_cli.run(META + spec + master, PLAN_MODEL,
                               timeout=int(os.environ.get("PLAN_TIMEOUT", "300")))
            m = re.search(r"\[.*\]", r["text"], re.S)
            tasks = json.loads(m.group(0)) if m else []
            assert isinstance(tasks, list) and tasks
        except Exception as e:
            sys.stderr.write(f"[planner] LLM decomposition failed ({e}); deterministic section-shard\n")
            tasks = _shard_by_sections(master) or [
                {"slug": "master-task", "prompt": master, "deps": [], "model_hint": "opus"}]
        if len(tasks) == 1 and len(master) > int(os.environ.get("PLAN_SHARD_MIN_CHARS", "6000")):
            sharded = _shard_by_sections(master)
            if len(sharded) >= 2:
                sys.stderr.write(f"[planner] single-task plan for {len(master)}-char prompt; "
                                 f"section-shard ({len(sharded)} tasks)\n")
                tasks = sharded

    # apply the profile's default model to any task that didn't declare one, cap the task count,
    # and stamp the workflow mode + materiality so downstream gates/observability can honor them.
    if prof:
        for t in tasks:
            t.setdefault("model_hint", default_model)
            t["workflow"] = prof.mode
            if prof.material:
                t["material"] = True
        if len(tasks) > prof.max_tasks and shard_mode == "full":
            # too many tasks for this lane — coarsen to the cap to reduce overhead.
            coarse = _shard_coarse(master, prof.max_tasks)
            if coarse:
                for t in coarse:
                    t["workflow"] = prof.mode
                    if prof.material:
                        t["material"] = True
                tasks = coarse

    # Apply TDD-first enforcement if configured
    tasks = _apply_tdd_gating(tasks)

    # Apply tests-first gate: split tasks whose proof references a missing test file
    tasks = tests_first_gate.apply_gate(tasks, repo_path=repo)

    # PREDICTIVE CONFLICT AVOIDANCE: feed currently-reserved files and predicted
    # conflicts back into task deps so the planner chains correctly.
    try:
        import file_reservation
        predictions = file_reservation.predict_conflicts()
        if predictions:
            hot_files = {p["file"] for p in predictions if p.get("risk") in ("high", "medium")}
            for t in tasks:
                scope_str = t.get("file_scope", "") or t.get("prompt", "")
                for hf in hot_files:
                    if hf in scope_str:
                        for other in tasks:
                            if other is t:
                                continue
                            other_scope = other.get("file_scope", "") or other.get("prompt", "")
                            if hf in other_scope and t.get("slug") not in (other.get("deps") or []):
                                other.setdefault("deps", []).append(t["slug"])
                                break
    except Exception as e:
        sys.stderr.write(f"[planner] predictive_conflict_avoidance failed ({e}); skipping\n")

    # STATIC FILE-SCOPE ANALYSIS: override/augment LLM-declared file scopes with
    # deterministic analysis. This catches the ~40% of cases where the LLM gets
    # file dependencies wrong, preventing merge conflicts before branches are created.
    if repo:
        try:
            import static_file_scope
            for t in tasks:
                analyzed = static_file_scope.override_scope(t, repo)
                if analyzed:
                    t["file_scope"] = ",".join(sorted(analyzed))
        except Exception as e:
            sys.stderr.write(f"[planner] static_file_scope failed ({e}); using LLM scopes\n")

    # DISPOSITION MEMORY (Wave C, Part 7): "branch closures train dedupe + planner so duplicate
    # work stops being GENERATED."
    #
    # This is the read side of the loop, and the only place the saving can actually be taken.
    # Closing a duplicate is cheap and teaches nothing; the fleet has been closing the same
    # duplicates for weeks and re-generating them the following week, because nothing consulted
    # the closure record before decomposing. Suppression is per-INITIATIVE, because the pattern
    # lives in the decomposition rather than in any one shard.
    #
    # Fail-soft and non-empty-guaranteed: if suppression would leave nothing to do we keep the
    # plan. A planner that can silently return zero tasks is worse than one that occasionally
    # re-does work.
    try:
        import platform_spine
        signal = _disposition_signal(project)
        if signal.get("by_initiative"):
            kept, dropped = [], []
            for t in tasks:
                allowed, reason = platform_spine.should_generate(t.get("slug"), signal)
                (kept if allowed else dropped).append(t if allowed else (t, reason))
            if dropped and kept:
                tasks = kept
                for t, reason in dropped:
                    sys.stderr.write(f"[planner] SUPPRESSED {t.get('slug')}: {reason}\n")
            elif dropped:
                sys.stderr.write("[planner] disposition memory would suppress every task; "
                                 "keeping the plan rather than returning nothing\n")
    except Exception as e:
        sys.stderr.write(f"[planner] disposition memory failed ({e}); planning unchanged\n")

    # GOLDEN PATHS + STRATEGY-AWARE GENERATION (Wave C, Part 4 — the compounding half).
    #
    # `golden_path.py` shipped complete, tested and dependency-free, and was imported by
    # NOTHING — the same dead-on-arrival shape the disposition-memory block above was in
    # before it was wired. Suppression (Part 7) stops waste being generated; this is the
    # other side, and the only place the compounding can actually be taken: it decides what
    # a shard STARTS from.
    #
    # Two clauses, both applied here because the prompt is the only artifact that reaches
    # the coder:
    #   * golden path — the best-OUTCOME merged shard in the vertical. The merged-diff
    #     library already answers "has something like this been done", but it ranks by
    #     similarity, and similarity is blind to outcome: a shard that merged after four
    #     repair attempts scores the same as one that merged first-pass.
    #   * approved structure — a tribunal approval is the most load-bearing context a shard
    #     can have and today is not passed down at all, so the AMOE flow and state gates get
    #     discovered as review findings instead of being written in the first place.
    #
    # Appended, never substituted: an existing prompt is what the operator asked for, and a
    # planner that rewrites it has changed the task rather than informed it. Fail-soft — a
    # missing strategy or a thin vertical leaves planning exactly as it was.
    tasks = _apply_golden_path(tasks, project=project)

    return tasks


def _apply_golden_path(tasks, project=None, strategy=None, shards=None):
    """Append golden-path + approved-structure context to each task prompt.

    Returns `tasks` unchanged on any failure or when there is nothing to add.
    """
    try:
        import golden_path
        strategy = strategy if strategy is not None else _approved_strategy(project)
        if not isinstance(strategy, dict) or not strategy.get("structure"):
            return tasks

        shards = shards if shards is not None else _merged_shards(project)
        vertical = strategy.get("vertical") or strategy.get("structure")
        template = golden_path.template_for(shards or [], vertical)

        context = golden_path.strategy_context(strategy, template=template)
        if not context.get("ok"):
            # An unapproved structure is a REFUSAL to add context, not a silent pass —
            # say so, because "built the wrong thing correctly" is the expensive failure.
            sys.stderr.write(f"[planner] golden path not applied: {context.get('reason')}\n")
            return tasks

        block = context.get("prompt") or ""
        if not block.strip():
            return tasks
        for t in tasks:
            prompt = str(t.get("prompt") or "")
            if "APPROVED STRUCTURE:" in prompt:
                continue                      # idempotent: re-planning must not stack blocks
            t["prompt"] = (block + "\n\n" + prompt) if prompt else block
        return tasks
    except Exception as e:
        sys.stderr.write(f"[planner] golden path failed ({e}); planning unchanged\n")
        return tasks


def _approved_strategy(project=None):
    """The tribunal-approved structure for this project, or {}. Fail-soft."""
    try:
        import db
        rows = db.select("strategies", {"select": "structure,vertical,approved,jurisdictions",
                                        "project": f"eq.{project}", "approved": "is.true",
                                        "order": "updated_at.desc", "limit": "1"}) or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def _merged_shards(project=None, limit=500):
    """Merged shards for outcome-ranked distillation, or []. Fail-soft."""
    try:
        import db
        rows = db.select("merged_diffs", {"select": "slug,project,kind,vertical,created_at",
                                          "project": f"eq.{project}",
                                          "order": "created_at.desc",
                                          "limit": str(int(limit))}) or []
        return rows
    except Exception:
        return []


def _disposition_signal(project=None, limit=500):
    """Closure history for this project, as a suppression signal. Fail-soft -> {}."""
    try:
        import db
        import platform_spine
        params = {"select": "slug,state,note", "limit": str(int(limit)),
                  "state": "in.(SUPERSEDED,QUARANTINED,BLOCKED,DONE)",
                  "order": "updated_at.desc"}
        rows = db.select("tasks", params) or []
        closures = [{"slug": r.get("slug"), "disposition": _disposition_of(r)} for r in rows]
        return platform_spine.disposition_signal(closures)
    except Exception:
        return {}


def _disposition_of(row):
    """Map a task row onto a disposition. Only WASTE is interesting here.

    A DONE task whose note says it was superseded is waste that happens to be recorded as
    success — the most common shape, and the one a naive `state == 'SUPERSEDED'` filter misses.
    """
    try:
        state = str((row or {}).get("state") or "").upper()
        note = str((row or {}).get("note") or "").lower()
        if state == "SUPERSEDED":
            return "superseded"
        for marker, disposition in (("duplicate", "duplicate"),
                                    ("superseded", "superseded"),
                                    ("already done", "already-done"),
                                    ("already present", "already-done"),
                                    ("no code target", "no-op"),
                                    ("obsolete", "obsolete")):
            if marker in note:
                return disposition
        return "merged"
    except Exception:
        return "merged"


def to_yaml(tasks: list) -> str:
    # dependency-ordered for readability (orchestrator/adaptive_run honors deps separately)
    hint = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
    lines = ["# generated by planner.py - review before running\n"]
    for t in tasks:
        lines.append(f"- slug: {t['slug']}")
        lines.append("  base: main")
        if t.get("model_hint"):
            lines.append(f"  model: {hint.get(t['model_hint'], t['model_hint'])}")
        if t.get("deps"):
            lines.append("  deps: [" + ", ".join(t["deps"]) + "]")
        prompt = t["prompt"].replace("\n", "\n    ")
        lines.append("  prompt: |\n    " + prompt)
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="-")
    ap.add_argument("--repo", default=None, help="repo path to read SPEC.md from")
    args = ap.parse_args()
    master = sys.stdin.read() if args.prompt == "-" else args.prompt
    if not master:
        sys.exit("usage: planner.py \"<master prompt>\"  (or - to read stdin)")
    print(to_yaml(plan(master, repo=args.repo)))
