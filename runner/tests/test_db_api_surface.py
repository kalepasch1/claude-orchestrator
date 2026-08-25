"""Every `db.<name>` a product module reaches for must exist on runner/db.py.

WHY THIS FILE EXISTS
--------------------
On 2026-08-25 an AST sweep found 44 product call sites reaching for functions
the db module has never defined: db.sql (13), db.query (17), db.execute (10),
db.delete (3), db.subscribe/unsubscribe (2).  db is a PostgREST client.  It has
no raw-SQL channel and never has; `def sql` has never appeared in db.py in the
repository's whole history (`git log -S"def sql(" -- runner/db.py` is empty).

Forty-three of the forty-four sat inside `except Exception:` handlers that
returned a default, so the AttributeError never surfaced.  The subsystems built
on them had therefore never worked, silently:

  * file_reservation.reserve() never wrote a row, so blocked_by() — which is
    correctly written against db.select — read an empty relation forever and
    the fleet's file-level mutual exclusion never blocked a single task.
  * result_cache.invalidate() invalidated nothing.
  * queue_groom.guard_duplicate_enqueue() was the one UNGUARDED site: it raised
    AttributeError into its caller from the day it was written, while its
    docstring called it "the primary fix for the 'groomed: duplicate queued
    slug' failure".

Their unit tests all passed, because the tests supplied the missing API
themselves: runner/tests/test_queue_groom.py installs `sys.modules['db']` with
`db_stub.sql = MagicMock(return_value=[])` and then asserts on the shape of the
SQL string handed to it.  A test that mocks a function into existence proves the
caller is self-consistent and proves nothing about whether it can run.

So the check has to be static, and it has to be about the REAL module.  This
file parses runner/db.py for the names it actually defines and parses every
tracked .py for the names it reaches for on `db`, and compares them.  Nothing is
imported and nothing is mocked, which is the point.

HOW THE REMAINING-WORK LIST BEHAVES
-----------------------------------
KNOWN_BROKEN below is an explicit file:line inventory, deliberately NOT a count.
A ceiling-on-a-count ratchet is what let the convention linter drift from 9,749
to 11,305 violations without failing once (see .pre-commit-config.yaml).  This
list fails in BOTH directions: a new bad call site is a failure, and a listed
site that has been fixed is also a failure until it is deleted from the list.
There is no way to be quietly wrong about it.
"""
import ast
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PY = os.path.join(ROOT, "runner", "db.py")


#: Call sites still reaching for a db API that does not exist, with what breaks.
#: Fix one -> delete its line here.  Add one -> this test fails.
KNOWN_BROKEN = {
    # db.query — raw SQL, 17 sites.  None of these modules is imported by
    # runner.py or any live loop; all are entered only by their own __main__.
    ("runner/bots/de_chancery.py", 72), ("runner/bots/de_chancery.py", 130),
    ("runner/config_drift.py", 92),
    ("runner/continuous_test.py", 152),
    ("runner/cx_determination_bundling.py", 107),
    ("runner/cx_tribunal_model.py", 99),
    ("runner/error_alerter.py", 98),
    ("runner/error_pattern_analyzer.py", 147), ("runner/error_pattern_analyzer.py", 153),
    ("runner/fleet_topology.py", 86),
    ("runner/kpi_regression_watchdog.py", 72),
    ("runner/metaopt.py", 29), ("runner/metaopt.py", 52),
    # db.sql — raw SQL, 9 remaining sites.  orchestration_api's four are
    # reimplementations of db.claim_task / db.heartbeat / db.count in SQL that
    # has never run; the real functions carry the economic ordering, host
    # affinity and schema-shape work these do not.
    ("runner/alert_rules_engine.py", 129),
    ("runner/config_sync.py", 233),
    ("runner/dynamic_tier_marginal_quality.py", 33),
    ("runner/fleet_health.py", 50),
    ("runner/investor_metrics_dashboard.py", 23),
    ("runner/metric_history.py", 211),
    ("runner/orchestration_api.py", 125), ("runner/orchestration_api.py", 133),
    ("runner/orchestration_api.py", 144), ("runner/orchestration_api.py", 159),
    ("runner/realtime_monitor.py", 30), ("runner/realtime_monitor.py", 81),
    # db.execute — raw SQL against a preview/prod promotion path.  Worth naming
    # separately: promote_preview_to_prod() and promote_or_rollback() have never
    # executed a statement, and both report success.
    ("runner/preview_promoter.py", 83), ("runner/preview_promoter.py", 112),
    ("runner/preview_promoter.py", 129), ("runner/preview_promoter.py", 140),
    ("runner/preview_promoter.py", 163),
    ("runner/preview_provisioner.py", 67), ("runner/preview_provisioner.py", 92),
    ("runner/promote_decision.py", 79), ("runner/promote_decision.py", 85),
    ("runner/promote_decision.py", 124),
    # db.subscribe/unsubscribe — a realtime API the PostgREST client never had.
    ("runner/realtime_approval_monitor.py", 165),
    ("runner/realtime_approval_monitor.py", 203),
}


def _tracked_py():
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True,
                                  timeout=60)
    return [p for p in out.split() if p]


def _db_surface():
    """Names runner/db.py binds at module level, by AST — nothing is imported."""
    tree = ast.parse(open(DB_PY, encoding="utf-8").read())
    surface, sigs = set(), {}

    def take(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            surface.add(node.name)
            a = node.args
            pos = [x.arg for x in a.posonlyargs] + [x.arg for x in a.args]
            sigs[node.name] = {
                "names": pos,
                "min": len(pos) - len(a.defaults),
                "max": None if a.vararg else len(pos),
            }
        elif isinstance(node, ast.ClassDef):
            surface.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    surface.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            surface.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                surface.add(al.asname or al.name.split(".")[0])

    for node in tree.body:
        take(node)
        # module-level try/if blocks bind names too
        if isinstance(node, (ast.If, ast.Try)):
            for sub in ast.walk(node):
                take(sub)
    return surface, sigs


def _locally_shadowed_lines(tree):
    """Lines inside a function that binds its own local named `db`.

    Several modules take a `db` parameter or build a dict called `db`; those
    attribute accesses are not about this module and must not be reported.
    """
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        binds = any(
            (isinstance(s, ast.Name) and s.id == "db" and isinstance(s.ctx, ast.Store))
            or (isinstance(s, ast.arg) and s.arg == "db")
            for s in ast.walk(node)
        )
        if binds:
            lines.update(s.lineno for s in ast.walk(node) if hasattr(s, "lineno"))
    return lines


def _is_test(rel):
    base = os.path.basename(rel)
    return base.startswith("test_") or "/tests/" in rel or rel.startswith("tests/")


def _module_db_accesses():
    """(rel, lineno, attr, call_node_or_None) for every `db.<attr>` in product code."""
    surface, _ = _db_surface()
    found = []
    for rel in _tracked_py():
        if _is_test(rel):
            continue
        path = os.path.join(ROOT, rel)
        try:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
        except (SyntaxError, OSError):
            continue
        skip = _locally_shadowed_lines(tree)
        calls = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "db"):
                calls[(node.func.lineno, node.func.attr)] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "db"):
                continue
            if node.lineno in skip:
                continue
            found.append((rel, node.lineno, node.attr, calls.get((node.lineno, node.attr))))
    return found


def test_db_py_still_defines_the_functions_this_test_reasons_about():
    """Guard the guard: if db.py is renamed or gutted, fail here, not silently."""
    surface, sigs = _db_surface()
    for name in ("select", "select_all", "count", "insert", "upsert", "update",
                 "delete", "rpc", "claim_task", "heartbeat"):
        assert name in surface, f"runner/db.py no longer defines {name}"
    assert sigs["update"]["names"] == ["table", "match", "patch"]
    assert sigs["upsert"]["names"] == ["table", "row"]
    assert sigs["delete"]["names"] == ["table", "match"]


def test_no_new_call_to_a_db_function_that_does_not_exist():
    surface, _ = _db_surface()
    bad = {(rel, ln) for rel, ln, attr, _ in _module_db_accesses() if attr not in surface}
    new = sorted(bad - KNOWN_BROKEN)
    assert not new, (
        "product code calls a db API that runner/db.py does not define:\n  "
        + "\n  ".join(f"{rel}:{ln}" for rel, ln in new)
        + "\n\ndb is a PostgREST client: it has select/select_all/count/insert/"
          "upsert/update/delete/rpc/claim_task/heartbeat and no raw-SQL channel. "
          "These calls raise AttributeError, and almost every historical instance "
          "sat inside `except Exception:` and was therefore invisible."
    )


def test_the_known_broken_list_has_no_stale_entries():
    """A fixed call site must be removed from KNOWN_BROKEN, not left to rot."""
    surface, _ = _db_surface()
    bad = {(rel, ln) for rel, ln, attr, _ in _module_db_accesses() if attr not in surface}
    stale = sorted(KNOWN_BROKEN - bad)
    assert not stale, (
        "these entries in KNOWN_BROKEN are no longer broken — delete them:\n  "
        + "\n  ".join(f"{rel}:{ln}" for rel, ln in stale)
        + "\n\n(If a line number merely moved, update it. The list is an inventory "
          "of remaining work, not a tolerance budget.)"
    )


def test_no_call_site_gets_the_argument_count_wrong():
    """Seven sites called update/upsert with the wrong arity and raised TypeError
    before touching the network, every one of them inside a try/except."""
    _, sigs = _db_surface()
    wrong = []
    for rel, ln, attr, call in _module_db_accesses():
        if call is None or attr not in sigs or attr.startswith("_"):
            continue
        if any(isinstance(a, ast.Starred) for a in call.args):
            continue
        if any(k.arg is None for k in call.keywords):
            continue
        sig = sigs[attr]
        kw_names = {k.arg for k in call.keywords}
        unknown_kw = kw_names - set(sig["names"])
        npos = len(call.args)
        supplied = npos + len(kw_names & set(sig["names"]))
        cap = sig["max"] if sig["max"] is not None else 10 ** 6
        if unknown_kw:
            wrong.append(f"{rel}:{ln} db.{attr} got unexpected keyword(s) "
                         f"{sorted(unknown_kw)}; signature is {attr}({', '.join(sig['names'])})")
        elif npos > cap or supplied < sig["min"]:
            wrong.append(f"{rel}:{ln} db.{attr} supplied {supplied} of "
                         f"{sig['min']}..{sig['max']}; signature is "
                         f"{attr}({', '.join(sig['names'])})")
    assert not wrong, "db call sites with the wrong arguments:\n  " + "\n  ".join(wrong)


@pytest.mark.parametrize("module,attr", [
    ("runner/queue_groom.py", "sql"),
    ("runner/file_reservation.py", "query"),
    ("runner/result_cache.py", "delete"),
])
def test_the_three_reachable_modules_no_longer_use_a_missing_api(module, attr):
    """Named explicitly: these three are the ones runner.py can actually reach."""
    surface, _ = _db_surface()
    tree = ast.parse(open(os.path.join(ROOT, module), encoding="utf-8").read())
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "db" and n.attr == attr and attr not in surface]
    assert not hits, f"{module} still calls db.{attr} at line(s) {hits}"
