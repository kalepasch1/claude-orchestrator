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
import error_handling_utils

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
        if not gated_kinds and tdd_gate.is_tdd_enabled():
            # Two config paths reach this gate: ORCH_TDD_REQUIRED_KINDS (fleet_config only) and
            # the older ORCH_TDD_ENABLED + ORCH_TDD_TASK_KINDS pair, which also honors env vars.
            # Consulting only the first meant a fleet configured the documented way had TDD
            # silently off — the gate reported "not configured" instead of gating.
            gated_kinds = tdd_gate.get_task_kinds()
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


#: Fallback acceptance test used when a shard's file scope tells us nothing more specific.
#: ORCH_-prefixed so it is fleet-pushable via fleet_control.py rather than edited per machine.
DEFAULT_ACCEPTANCE_TEST = os.environ.get(
    "ORCH_DEFAULT_ACCEPTANCE_TEST", "python3 -m pytest runner/tests -q")

#: Proof strings a model emits that read like an acceptance test but cannot be executed.
#: These are treated as MISSING, because an unrunnable proof is what lets a shard land with
#: "tests pass" asserted by nobody.
_VAGUE_PROOFS = (
    "tests pass", "test passes", "suite green", "all tests pass", "n/a", "none",
    "manual", "manual verification", "verify manually", "tbd", "todo", "build passes",
)

_TEST_FILE_RE = re.compile(r'(?:^|[,\s/])((?:[\w./-]*/)?tests?/[\w./-]*test_[\w.-]+\.py)')
_PY_FILE_RE = re.compile(r'(?:^|[,\s])((?:[\w./-]*/)?([\w-]+)\.py)')


def _is_concrete_proof(proof) -> bool:
    """A proof is concrete only if it is a non-trivial string that is not one of the
    known hand-wave phrases. Fail-soft: anything unparseable is 'not concrete', which
    only ever causes us to ATTACH a test, never to drop one."""
    if not isinstance(proof, str):
        return False
    stripped = proof.strip()
    if len(stripped) < 8:
        return False
    return stripped.lower().rstrip(".") not in _VAGUE_PROOFS


def _derive_acceptance_test(task) -> str:
    """Derive a runnable acceptance test command for one planned shard.

    Preference order, most specific first:
      1. a test file named in the task's file scope / prompt -> run exactly that file
      2. a source file named there -> run its conventional sibling suite
      3. DEFAULT_ACCEPTANCE_TEST
    """
    scope = ""
    try:
        scope = "%s %s" % (task.get("file_scope", "") or "", task.get("prompt", "") or "")
    except Exception:
        return DEFAULT_ACCEPTANCE_TEST

    m = _TEST_FILE_RE.search(scope)
    if m:
        return "python3 -m pytest %s -q" % m.group(1)

    for full, stem in _PY_FILE_RE.findall(scope):
        if "test" in stem:
            continue
        prefix = full.rsplit("/", 1)[0] + "/" if "/" in full else ""
        return "python3 -m pytest %stests/test_%s.py -q" % (prefix, stem)

    return DEFAULT_ACCEPTANCE_TEST


def ensure_acceptance_tests(tasks):
    """Guarantee that EVERY independently-buildable shard carries its own concrete,
    runnable acceptance test.

    The planner prompt asks the model for one, but nothing enforced it, so shards
    routinely arrived with no `proof` at all (or "tests pass", which no runner can
    execute). A shard with no acceptance test is not independently verifiable, which
    is the entire point of splitting the build task up in the first place.

    Never overwrites a proof that is already concrete. Fail-soft: on any error the
    task list is returned untouched — a planner that raises here would wedge intake.
    """
    if not tasks:
        return tasks
    try:
        for t in tasks:
            if not isinstance(t, dict):
                continue
            if _is_concrete_proof(t.get("proof")):
                continue
            t["proof"] = _derive_acceptance_test(t)
    except Exception as e:
        sys.stderr.write(f"[planner] ensure_acceptance_tests failed ({e}); proofs unchanged\n")
    return tasks


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
            except PermissionError as exc:
                # Named before the bare `except Exception: pass` below so an
                # unreadable CLAUDE.md is reported rather than silently dropped.
                wrapped = error_handling_utils.wrap_error(
                    exc, context=f"reading {cmd_path}")
                sys.stderr.write(
                    f"[planner] CLAUDE.md access denied ({wrapped}); "
                    f"fail-soft, continuing\n")
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

    # GOLDEN PATHS + STRATEGY-AWARE GENERATION (Wave C, Part 4, compounding half).
    tasks = _apply_golden_path(tasks, project=project, repo=repo)

    # Last pass, deliberately: every shard leaves the planner with a runnable acceptance
    # test, whatever earlier passes did to the plan (sharding, coarsening, golden paths and
    # suppression all mint or rewrite tasks, and any of them can drop a proof).
    tasks = ensure_acceptance_tests(tasks)

    return tasks


#: Sentinel that makes golden-path injection idempotent across re-plans. A task that is
#: re-planned (remediation, requeue) must not accumulate one context block per attempt —
#: that is how a 6k prompt becomes a 40k prompt and the shard compaction-spirals.
GOLDEN_PATH_MARKER = "<!-- wave-c/golden-path -->"


def _apply_golden_path(tasks, project=None, repo=None):
    """Append the vertical's golden-path template + approved-structure requirements to
    every shard prompt (Wave C, Part 4, clauses 3 and 4).

    `golden_path.py` shipped complete and tested in slice 4 and was then imported by
    NOTHING — Part 7 suppression got wired into plan(), Part 4 generation did not. So the
    fleet kept starting shards from the most SIMILAR prior diff rather than the best-OUTCOME
    one, and kept discovering missing AMOE flows and state gates at the compliance gate
    instead of generating them. This is the wiring.

    Fail-soft: any failure leaves `tasks` exactly as it was received.
    """
    try:
        import golden_path
    except Exception as e:
        sys.stderr.write(f"[planner] golden_path unavailable ({e}); generation unchanged\n")
        return tasks

    try:
        vertical = project or None
        template = golden_path.template_for(_merged_shards(project), vertical) if vertical else None
        strategy = _approved_strategy(project, repo)
        context = golden_path.strategy_context(strategy, template)

        if not context.get("ok"):
            # LOUD REFUSAL. An unapproved structure is the expensive case: the shard would be
            # built correctly against the wrong thing. Say so; do not inject a half-context.
            if str((strategy or {}).get("structure") or "").strip():
                sys.stderr.write(f"[planner] GOLDEN PATH REFUSED: {context.get('reason')}\n")
            if not template:
                return tasks
            block = (f"GOLDEN PATH: start from {template.get('slug')} — the best-outcome merged "
                     f"shard in {vertical}, not merely the most similar one "
                     f"(outcome_score={template.get('outcome_score')}).")
        else:
            block = context["prompt"]

        injected = 0
        for t in tasks:
            prompt = t.get("prompt") or ""
            if GOLDEN_PATH_MARKER in prompt:
                continue                      # already carries this context; re-plan is a no-op
            t["prompt"] = f"{prompt}\n\n{GOLDEN_PATH_MARKER}\n{block}\n"
            if context.get("structure"):
                t["structure"] = context["structure"]
            if template:
                t["golden_template"] = template.get("slug")
            injected += 1

        if injected:
            sys.stderr.write(
                f"[planner] golden path: {injected} shard(s) carry "
                f"structure={context.get('structure') or '-'} "
                f"template={ (template or {}).get('slug') or '-' }\n")
        return tasks
    except Exception as e:
        sys.stderr.write(f"[planner] golden path failed ({e}); generation unchanged\n")
        return tasks


def _merged_shards(project=None, limit=500):
    """Past shards of this project as golden_path outcome records. Fail-soft -> []."""
    try:
        import db
        params = {"select": "slug,state,note,attempt,remediation_count,build_fail_count,"
                            "created_at,updated_at",
                  "limit": str(int(limit)),
                  "state": "in.(MERGED,DONE)",
                  "order": "updated_at.desc"}
        shards = []
        for row in db.select("tasks", params) or []:
            note = str(row.get("note") or "").lower()
            shards.append({
                "slug": row.get("slug"),
                "vertical": project,
                "merged": True,
                "reverted": "revert" in note,
                "attempts": int(row.get("attempt") or 0) + 1,
                "review_cycles": int(row.get("remediation_count") or 0),
                "test_pass": not int(row.get("build_fail_count") or 0),
                "days_to_merge": _days_between(row.get("created_at"), row.get("updated_at")),
            })
        return shards
    except Exception:
        return []


def _days_between(start, end):
    """Whole-ish days between two ISO timestamps. 0.0 when either is unusable."""
    try:
        from datetime import datetime
        def _parse(value):
            text = str(value or "").replace("Z", "+00:00")
            return datetime.fromisoformat(text)
        return max(0.0, (_parse(end) - _parse(start)).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _approved_strategy(project=None, repo=None):
    """The tribunal-approved structure for this project, or {}.

    There is no strategies table yet, so the approval lives where a human can see and edit
    it: `<repo>/.orchestrator/strategy.json`, overridable per-run by ORCH_APPROVED_STRUCTURE
    (+ ORCH_STRUCTURE_APPROVED_BY, ORCH_STRUCTURE_JURISDICTIONS). Absent approval, this
    returns {} and strategy_context() refuses — which is the correct default: silently
    generating against an unapproved structure is the failure this clause exists to prevent.
    """
    structure = os.environ.get("ORCH_APPROVED_STRUCTURE", "").strip()
    if structure:
        approver = os.environ.get("ORCH_STRUCTURE_APPROVED_BY", "").strip()
        juris = [j.strip() for j in os.environ.get("ORCH_STRUCTURE_JURISDICTIONS", "").split(",")
                 if j.strip()]
        return {"structure": structure, "approved": bool(approver),
                "approved_by": approver, "jurisdictions": juris, "project": project}
    if not repo:
        return {}
    try:
        path = os.path.join(repo, ".orchestrator", "strategy.json")
        if not os.path.isfile(path):
            return {}
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        sys.stderr.write(f"[planner] strategy.json unreadable ({e}); no approved structure\n")
        return {}


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
