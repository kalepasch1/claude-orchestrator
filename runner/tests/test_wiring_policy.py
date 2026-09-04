"""wiring_policy, and its wiring into the planner.

Two things are being held. First, that the policy actually distinguishes a
module with a caller from one without — a scanner that reports everything, or
nothing, as unwired is worse than no scanner, because the planner would learn to
ignore it.

Second, and more important on this path: every function is fail-soft. This is
planner code. An unreadable file or a `repo=None` must degrade to "no wiring
context this run", never to a planner that cannot plan, so the failure cases
below are checked as carefully as the success ones.
"""
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import wiring_policy as wp  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path)
    write(os.path.join(root, "server/utils/pricing.ts"), "export const x = 1")
    write(os.path.join(root, "server/utils/orphan.ts"), "export const y = 2")
    write(os.path.join(root, "server/utils/index.ts"), "export * from './pricing'")
    write(os.path.join(root, "server/api/quote.post.ts"), "import { x } from '~/server/utils/pricing'")
    return root


# ── the public surface the rest of the feature builds against ───────────────

def test_the_constants_are_the_agreed_contract():
    assert wp.LOGIC_DIRS == ("server/utils", "server/engines", "lib", "runner")
    assert wp.SURFACE_DIRS == ("server/api", "pages", "components", "app")


def test_the_wiring_rule_is_final_text_not_a_stub():
    rule = wp.WIRING_RULE
    assert rule.startswith("WIRING RULE (mandatory):")
    # The merge-time checker quotes this; the phrasings below are load-bearing.
    assert "the engine and its surface are one atomic deliverable" in rule
    assert "wiring_check.py" in rule
    for logic_dir in wp.LOGIC_DIRS:
        assert logic_dir in rule


def test_the_module_documents_the_cli_and_config_contracts():
    doc = wp.__doc__ or ""
    for flag in ("--root", "--strict", "--json"):
        assert flag in doc
    assert "Total=N Wired=N Orphans=N" in doc
    for key in ("framework", "autoImportDirs", "logicDirs", "surfaceDirs", "exceptions"):
        assert key in doc


# ── _build_import_context ───────────────────────────────────────────────────

def test_it_separates_a_called_module_from_an_orphan(repo):
    ctx = wp._build_import_context(repo)
    # orphan.ts has no caller; pricing.ts is imported by server/api/quote.post.ts.
    assert "UNWIRED  server/utils/orphan.ts" in ctx
    assert "UNWIRED  server/utils/pricing.ts" not in ctx
    assert "1 UNWIRED modules" in ctx
    assert "1 wired modules (OK)" in ctx


def test_index_files_are_not_reported_as_orphans(repo):
    # index.ts IS the barrel export. Counting it as unwired logic would report
    # every package root as an orphan and train the reader to ignore the list.
    assert "index.ts" not in wp._build_import_context(repo)


def test_output_is_capped_on_a_line_boundary(tmp_path):
    root = str(tmp_path)
    for i in range(400):
        write(os.path.join(root, f"lib/mod_{i}.ts"), "x")
    ctx = wp._build_import_context(root, max_chars=500)
    assert len(ctx) <= 520
    assert "truncated" in ctx
    # Never ends mid-path.
    assert not ctx.rstrip().endswith("mod_")


@pytest.mark.parametrize("bad", [None, "", "/does/not/exist", 42, object()])
def test_a_bad_repo_yields_no_context_and_no_exception(bad):
    assert wp._build_import_context(bad) == ""


def test_an_empty_repo_yields_no_context(tmp_path):
    assert wp._build_import_context(str(tmp_path)) == ""


def test_an_unreadable_surface_file_does_not_lose_the_scan(repo, monkeypatch):
    real_open = open

    def flaky(path, *args, **kwargs):
        if "quote.post.ts" in str(path):
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky)
    ctx = wp._build_import_context(repo)
    # Surface unreadable => everything looks unwired, but we still get a report.
    assert "UNWIRED" in ctx


# ── _apply_wiring_reminders ─────────────────────────────────────────────────

def test_a_logic_only_task_gets_the_reminder():
    tasks = [{"prompt": "edit server/utils/foo.ts"}]
    out = wp._apply_wiring_reminders(tasks)
    assert wp.WIRING_REMINDER in out[0]["prompt"]


def test_a_task_that_already_names_its_surface_is_left_alone():
    prompt = "create server/utils/foo.ts and server/api/foo.post.ts"
    out = wp._apply_wiring_reminders([{"prompt": prompt}])
    assert out[0]["prompt"] == prompt


def test_a_task_touching_no_logic_is_left_alone():
    out = wp._apply_wiring_reminders([{"prompt": "update the README"}])
    assert wp.WIRING_REMINDER not in out[0]["prompt"]


def test_the_reminder_is_not_appended_twice():
    tasks = [{"prompt": "edit lib/thing.ts"}]
    wp._apply_wiring_reminders(tasks)
    wp._apply_wiring_reminders(tasks)
    assert tasks[0]["prompt"].count(wp.WIRING_REMINDER) == 1


@pytest.mark.parametrize("tasks", [None, [], [{}], [{"prompt": None}], ["not-a-dict"], [None]])
def test_malformed_task_lists_pass_through_unchanged(tasks):
    assert wp._apply_wiring_reminders(tasks) is tasks


# ── augment_plan ────────────────────────────────────────────────────────────

def test_augment_plan_returns_context_and_tasks(repo):
    ctx, tasks = wp.augment_plan([{"prompt": "edit server/utils/foo.ts"}], repo)
    assert isinstance(ctx, str) and "UNWIRED" in ctx
    assert wp.WIRING_REMINDER in tasks[0]["prompt"]


def test_augment_plan_always_returns_a_two_tuple():
    # The planner unpacks this. A one-value return would raise there, at the
    # worst possible moment, which is exactly what fail-soft is meant to prevent.
    for args in [([], None), (None, None), (None, "/nope"), ([{"prompt": "x"}], 42)]:
        result = wp.augment_plan(*args)
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], str)


# ── the planner wiring itself ───────────────────────────────────────────────

def test_planner_imports_cleanly():
    """The task's stated acceptance criterion."""
    import planner  # noqa: F401


def test_the_planning_prompt_carries_the_rule():
    import planner
    assert wp.WIRING_RULE in planner.META
    # Between the existing META body and the REQUEST marker, in that order.
    assert planner.META.index("structurally conflict at merge time.") \
        < planner.META.index(wp.WIRING_RULE) \
        < planner.META.index("REQUEST:")


def test_planner_calls_augment_plan_after_tdd_gating():
    source = open(os.path.join(RUNNER, "planner.py"), encoding="utf-8").read()
    assert source.index("_apply_tdd_gating(tasks)") < source.index("wiring_policy.augment_plan(tasks, repo)")
    assert "wiring_policy._build_import_context(repo)" in source
