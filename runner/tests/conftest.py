# conftest.py provides shared fixtures for all runner tests.
"""Suite-wide isolation for tests that mutate process-global state."""
import os
import sys
import pytest

import db as _real_db
import kill_switch as _real_kill_switch
import log as _real_log
import subscription_guard as _real_subscription_guard
import provider_terms as _real_provider_terms
import tdd_gate as _real_tdd_gate

_PROVIDER_DEFAULTS = {
    name: dict(metadata) for name, metadata in _real_provider_terms.DEFAULTS.items()
}


#: Gate kill-switches. Every one exists to turn a guard OFF, so inheriting one
#: from the machine means testing a system with that guard already disabled.
_GATE_KILL_SWITCHES = (
    "ORCH_DISABLE_TOOLCHAIN_GATE",
    "ORCH_DISABLE_MEM_GATE",
    "ORCH_DISABLE_LOCAL_MODELS",
    "ORCH_DISABLE_VERCEL_CHECKS_CACHE",
)


@pytest.fixture(autouse=True, scope="session")
def _tests_never_write_to_the_live_runtime_dir(tmp_path_factory):
    """Point every runtime writer at a temp dir for the whole session.

    94 modules resolve their state and log paths from CLAUDE_ORCH_HOME, defaulting
    to the repo's .runtime/. Nothing overrode it under pytest, so guard tests
    appended their fixtures straight into the production log files. By 2026-08-30
    the tails of automerge-discard-guard.log, divergent-authorship-guard.log and
    vercel-config-guard.log were pure test noise — rows naming /tmp/tmpXXXX repos,
    branch "topic", file "f.py", project "test" — sitting in 10-14MB files that an
    operator reads to find out what the fleet actually did. Reading those tails on
    2026-08-30 I concluded the guards had never run against a real repo at all;
    they had, and the fixtures were burying the evidence.

    Session-scoped so it lands before the per-test env snapshot in
    _restore_environment_after_test, which then restores this value rather than
    the machine's.
    """
    sandbox = tmp_path_factory.mktemp("orch-runtime")
    os.environ["CLAUDE_ORCH_HOME"] = str(sandbox)
    os.environ.setdefault("ORCH_SCOREBOARD_DIR", str(sandbox))
    yield sandbox


@pytest.fixture(autouse=True)
def _gates_are_on_unless_a_test_says_otherwise(monkeypatch):
    """A gate must not be off just because this machine has it off.

    Importing almost anything under runner/ pulls in db, whose _load_env() reads
    runner/.env into os.environ. That file is gitignored and machine-local: 260
    keys, 230 of them read by tracked product code, and only 30 also set by a
    test. So roughly two hundred configuration values that no reviewer sees can
    decide a test's verdict.

    Found the concrete way: runner/.env line 520 sets
    ORCH_DISABLE_TOOLCHAIN_GATE=1, so toolchain_gate.is_ready_cached() returned
    True for everything and the two tests in test_toolchain_gate.py that expected
    a BLOCK had been failing. The ones expecting True kept passing, which is why
    it read as a logic bug rather than an environment one — every assertion was
    satisfied by "always returns True".

    Only the DISABLE switches are cleared, and only these four: their whole
    purpose is to turn a guard off, so a suite that inherits one is testing a
    system with that guard already gone. Everything else in .env is left alone —
    neutralising 230 keys would break tests that legitimately depend on the
    machine's configuration, and this is a guard, not a sandbox. A test that
    wants the disabled path sets the variable itself with patch.dict, which
    takes effect after this fixture and wins.
    """
    for name in _GATE_KILL_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def _runner_stays_a_package():
    """See _keep_runner_importable_as_a_package. Runs before every test."""
    _keep_runner_importable_as_a_package()
    yield


@pytest.fixture(autouse=True)
def _restore_environment_after_test():
    """A test's routing/config overrides must never affect later tests."""
    before = dict(os.environ)
    _real_provider_terms.DEFAULTS.clear()
    _real_provider_terms.DEFAULTS.update(
        {name: dict(metadata) for name, metadata in _PROVIDER_DEFAULTS.items()}
    )
    sys.modules["provider_terms"] = _real_provider_terms
    yield
    os.environ.clear()
    os.environ.update(before)


@pytest.fixture(autouse=True)
def _reset_projects_cache():
    """A test's mocked `projects` rows must never leak into the next test.

    db.claim_task reads the project list through db._refresh_projects_cache(), a
    module-global memo with a 300s TTL. The memo is keyed on nothing but time, so
    the FIRST test to call claim_task populates it and every later test in the same
    session silently reuses those rows — its own patched db.select("projects") is
    never consulted.

    That is invisible until a test supplies non-default projects. Host affinity then
    computes local_repo_pids from the STALE ids, no queued task matches, claim_task
    filters the whole queue away and returns None. test_pinned_express_lane's
    test_multiple_projects_with_pinned_express_lane and
    test_paused_project_filtering_happens_before_express_lane failed exactly this way
    — both pass in isolation, both fail in-suite, and whichever ran first was the one
    that passed. Two red tests in the merge gate for every branch, with a symptom
    ("no locally-runnable tasks") that points at host affinity rather than at cache
    bleed.

    Clearing the memo before each test makes the patched select authoritative again.
    """
    _real_db._cached_projects_list = []
    _real_db._PROJECT_CACHE_TIME["at"] = 0
    yield
    _real_db._cached_projects_list = []
    _real_db._PROJECT_CACHE_TIME["at"] = 0


@pytest.fixture(autouse=True)
def _db_breaker_starts_closed():
    """No test inherits another test's opinion that the control plane is down.

    db's circuit breaker is process-global on purpose: one thread discovering the
    origin is unreachable spares every other thread the full timeout. Inside a test
    session that reach makes any test which touches the real origin a trap for every
    test after it — ten consecutive unreachable calls open the breaker for its whole
    cooldown, and from then on db._req raises ControlPlaneDown before reaching the
    code under test.

    Seen twice in one session: test_db_retries::test_get_retries_transient_dns_failure
    never got to count its retries, and test_crash_loop_detector's task write died on
    a breaker someone else had opened. Both pass alone.

    Reset BEFORE the test, not after, so a test that deliberately opens the breaker
    (test_db_breaker_writes) still owns its own state while it runs.
    """
    _real_db.reset_breaker()
    yield


@pytest.fixture(autouse=True)
def _evict_leaked_module_doubles():
    """Put back any real runner module a test swapped for a Mock and did not restore.

    _restore_real_modules() already runs at every module boundary, which is enough for a
    fake installed at import time. It is not enough for a double installed and leaked
    INSIDE a test — a threaded patch.dict whose restores interleave, or a test that raises
    before its context manager unwinds. Those leak for the remainder of the session and
    the symptom lands on some unrelated file much later.

    Only Mock-shaped stand-ins are evicted here; a types.ModuleType fake is the deliberate
    module-scope convention in this suite and is left alone until the next module boundary.
    """
    yield
    _evict_stub_shadows()
    _reinstate_missing_real_modules()


def _reinstate_missing_real_modules():
    """Put back a remembered module that a test DELETED from sys.modules.

    THE DUPLICATE-MODULE LEAK (2026-08-25). _evict_stub_shadows above handles a
    real module replaced by a double. It does nothing for a real module simply
    removed, and removal is the more damaging of the two, because Python does not
    leave a hole: the next `import db` anywhere builds a SECOND module object from
    the same source, and from then on the session has two live copies of the
    control-plane client.

    Every module that imported db earlier keeps copy A -- including this
    conftest's own _REAL_MODULES registry and every test file's module-level
    `import db`. Any code that does `import db` INSIDE a function then resolves
    copy B. A test that patches db.select on the object it holds is patching A
    while the code under test reads B, so the patch silently does nothing and the
    product runs against the real client. It passes alone and fails in suite, and
    the failure lands on whichever file happens to come later.

    Found via runner/tests/test_db_env_interlock.py, which popped "db" and
    "subscription_guard" to import throwaway copies and never put the originals
    back -- 20 failures across two unrelated files. That file is fixed, but a
    hole in sys.modules is never something a test wants left behind, so it is
    also closed here rather than only at its one known source.

    Deliberately narrow: only names already in _REAL_MODULES (so it can only ever
    restore something this session actually had) and only when the name is ABSENT
    (a test that installed its own double keeps it; that is _evict_stub_shadows'
    job, on its own rules).
    """
    for name, module in _REAL_MODULES.items():
        if name not in sys.modules:
            sys.modules[name] = module


@pytest.fixture(autouse=True)
def _reset_tdd_gate_cache():
    """tdd_gate memoizes its fleet_config reads for 30s on module globals.

    Same shape as the projects memo above: the FIRST test to call get_required_kinds()
    populates the memo, and every later test in the session gets that value back instead
    of its own patched db.select. test_tdd_gate's test_caches_result_for_30s asserts a
    DB call count, so it passes alone and fails in-suite depending purely on which file
    ran first — one more permanently-red test in the merge gate with a misleading symptom.
    """
    _real_tdd_gate.invalidate_cache()
    yield
    _real_tdd_gate.invalidate_cache()


# Control-plane modules a test replaced via sys.modules[...] = ModuleType(...).
#
# This used to be a hand-written list with the instruction "keep in sync with
# grep -rhoE 'sys\.modules\["[a-z_]+"\] *=' runner/tests/*.py". It was not in sync,
# and a list maintained by grep never will be: the five names below were registered
# and twelve more were not. test_monthly_audit.py alone installs empty stubs for
# model_policy, model_gateway, claude_cli, queue_counters and prompt_assembler at
# IMPORT time and never removes them, so every test module collected after it saw a
# `model_policy` with nothing in it — which is why ~35 files passed alone and failed
# in-suite with errors like "cannot import name revenue_keywords".
#
# So the registry learns instead. Any module that lives under runner/ and is real
# (has a __file__) gets remembered the first time we see it; if a later test swaps it
# for a stub, the real one goes back before the next module is imported. Nothing has
# to be listed by hand, and a new polluting test cannot silently widen the blast
# radius.
_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_REAL_MODULES = {
    "db": _real_db,
    "kill_switch": _real_kill_switch,
    "log": _real_log,
    "subscription_guard": _real_subscription_guard,
    "provider_terms": _real_provider_terms,
}


def _is_real_runner_module(module):
    """True for an imported module whose source file lives in runner/."""
    path = getattr(module, "__file__", None)
    if not path:
        return False
    try:
        return os.path.dirname(os.path.abspath(path)) == _RUNNER_DIR
    except Exception:
        return False


def _remember_real_modules():
    for name, module in list(sys.modules.items()):
        if "." in name or name in _REAL_MODULES:
            continue
        if _is_real_runner_module(module):
            _REAL_MODULES[name] = module


def _evict_stub_shadows():
    """Drop synthetic stand-ins that shadow a real runner/ module.

    Remembering is not enough on its own: a test that stubs a module the suite has
    never imported (test_monthly_audit stubs model_policy at import time, and nothing
    before it imports model_policy) leaves nothing to restore. Here the stub — a bare
    ModuleType with no __file__, for a name that has a real runner/<name>.py behind it
    — is simply evicted, so the next `import <name>` loads the real source. Stubs for
    modules that do NOT live in runner/ (a fake `requests`, say) are left alone; they
    shadow nothing this suite owns.
    """
    for name, module in list(sys.modules.items()):
        if "." in name or module is None:
            continue
        if not os.path.isfile(os.path.join(_RUNNER_DIR, f"{name}.py")):
            continue
        if not _is_stand_in(module):
            continue
        real = _REAL_MODULES.get(name)
        if real is not None:
            sys.modules[name] = real
        else:
            del sys.modules[name]


def _is_stand_in(module):
    """True when this sys.modules entry is a test double rather than a real module.

    Two shapes, and the second is the one that got away. A `types.ModuleType` with no
    __file__ is the documented fake in this suite. A MagicMock is not a module at all —
    and it answers `getattr(m, "__file__")` with another Mock, so a __file__ check reads
    it as real and leaves it in place.

    That is not hypothetical: test_canary_ollama_22 runs `patch.dict(sys.modules, {"db":
    MagicMock()})` inside five concurrent threads, and patch.dict restores by clearing and
    re-filling the dict — interleaved restores park the mock in sys.modules["db"] for the
    rest of the session. Every later `@patch("db.select")` then patches the leftover mock
    while the real db runs unpatched and reaches for a live database.
    """
    import types
    if not isinstance(module, types.ModuleType):
        return True
    return not getattr(module, "__file__", None)


def _restore_real_modules():
    _remember_real_modules()
    sys.modules.update(_REAL_MODULES)
    _evict_stub_shadows()


#: The repository root, which must stay AHEAD of runner/ on sys.path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNNER_DIR = os.path.join(_REPO_ROOT, "runner")


def _keep_runner_importable_as_a_package():
    """Ensure `runner` still names the PACKAGE, not runner/runner.py.

    Both spellings are in use across this suite. A test that does
    `import task_state_machine` needs runner/ on sys.path; a test that does
    `from runner.task_state_machine import ...` needs the repo root on it. Both
    can be present — what decides which module the name `runner` resolves to is
    which comes FIRST.

    Nearly every test file does a `sys.path.insert(0, ...)` at module scope and
    none of them undo it, so the winner is simply whichever file was imported
    most recently. runner/tests/test_python39_compat.py inserted runner/ at
    position 0 and sorts late in the collection order, so from that point on
    `runner` resolved to runner/runner.py — a module with no __path__ — and
    every later `from runner.X import Y` died with

        ModuleNotFoundError: No module named 'runner.X'; 'runner' is not a package

    That is 35 failures across six files, every one of which passes in
    isolation: test_done_to_merged_conversion, test_route_consolidation,
    test_branch_recovery_validate_repository, test_task_state_machine,
    test_repo_access_healer and test_train_status_backfill.

    Rather than police 700 files' sys.path edits, restore the ORDER here, before
    each TEST runs. runner/ is left in place, so the bare-name imports keep
    working; only the precedence is asserted.

    Per test, not per module: the victims' `from runner.X import Y` sits inside
    the test methods, and test_python39_compat's damage is done in its own test
    body — it imports all ~910 runner modules, dozens of which insert runner/ at
    sys.path[0] at their own import time. A collection-time repair is undone
    before the first victim runs.
    """
    if not os.path.isdir(_RUNNER_DIR):
        return

    # 1. Precedence on sys.path.
    if _RUNNER_DIR in sys.path:
        runner_at = sys.path.index(_RUNNER_DIR)
        if _REPO_ROOT not in sys.path[:runner_at]:
            while _REPO_ROOT in sys.path:
                sys.path.remove(_REPO_ROOT)
            sys.path.insert(sys.path.index(_RUNNER_DIR), _REPO_ROOT)

    # 2. Evict a `runner` already bound to runner/runner.py.
    #
    # Fixing the path alone is not enough, and this is the half that is easy to
    # miss: once sys.modules["runner"] holds the MODULE runner/runner.py, the
    # import system finds it there and never consults sys.path again, so
    # `import runner.X` keeps failing with a corrected path. It is also invisible
    # to _evict_stub_shadows(), which looks for fakes without a __file__ — this
    # entry is a real module, just the wrong one for the name.
    bad = sys.modules.get("runner")
    if bad is not None and not hasattr(bad, "__path__"):
        del sys.modules["runner"]


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makemodule(module_path, parent):
    """Prevent synthetic control-plane modules from leaking into later modules."""
    yield
    _restore_real_modules()
    _keep_runner_importable_as_a_package()


@pytest.hookimpl(hookwrapper=True)
def pytest_collectstart(collector):
    """Restore real control-plane modules BEFORE each test module is imported.

    Several modules (test_hive_candidates_ops_page, test_source_config_validator)
    install a synthetic `db` at import time via sys.modules["db"] = ModuleType("db").
    pytest_pycollect_makemodule alone is not enough: under pytest 8 the module body
    executes in Module.collect(), i.e. AFTER that hook's post-yield restore. So the
    fake `db` leaked into every module imported afterwards, and any later
    `from db import <name>` died with "cannot import name ... (unknown location)".

    That made whole-suite collection fail while each file passed in isolation —
    which silently broke the merge gate (pytest) for every branch. Restoring on
    collectstart closes the window. Rebinding sys.modules does not affect modules
    that already bound their own reference at import, so the polluting tests keep
    working against their fakes.
    """
    if isinstance(collector, pytest.Module):
        _restore_real_modules()
        _keep_runner_importable_as_a_package()
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Hermetic execution: no live network, no unbounded subprocess.
#
# This suite reached out to the real internet. blocked_triage's release-currency
# scan shells out to `git ls-remote --heads origin` per project, so running the
# tests took a trip to GitHub and back, once per repo. Two consequences, both
# bad, and both observed:
#
#   - Suite duration became a function of GitHub's latency. Two pytest runs at
#     once starved each other and looked exactly like a hang.
#   - A network blip is indistinguishable from a real failure. That is how a red
#     suite turns into background noise nobody reads.
#
# A unit test that needs the network is a unit test that is lying about what it
# covers. Both guards below fail LOUDLY and name the fix, rather than silently
# returning a stub — a stub would make the test pass while testing nothing.
#
# Opt out per test with @pytest.mark.allow_network when a test genuinely needs
# a real socket. There is no opt-out for the missing-timeout guard: add the
# timeout.
# ─────────────────────────────────────────────────────────────────────────────
import ipaddress as _ipaddress
import socket as _socket
import subprocess as _subprocess
import warnings


class NetworkAccessInTest(ConnectionRefusedError):
    """A test tried to open a real socket.

    Deliberately a ConnectionRefusedError — an OSError — and not a bare
    RuntimeError.

    The first version raised RuntimeError, which no caller in this codebase is
    written to expect. Code that already handles being offline (this fleet is
    fail-soft nearly everywhere) took an error path it has no branch for, and
    tests that had been passing went red for the wrong reason: not because they
    needed the network, but because they were handed an exception no production
    caller could ever see.

    An offline machine refuses the connection. Simulating exactly that means
    fail-soft code follows the branch it would really follow, and only code that
    genuinely CANNOT proceed without a remote host fails — which is the signal
    this guard exists to produce.
    """


class UnboundedSubprocessInTest(UserWarning):
    """A test spawned a subprocess with no timeout; one was supplied for it."""


# Loopback is not "somebody else's uptime".
#
# A test that binds an ephemeral port on 127.0.0.1 and then talks to it — which
# is the only honest way to test an HTTP handler end to end — depends on nothing
# outside this process. Refusing it made the guard fail the exact tests it was
# never aimed at (canary.start_metrics_server()'s five request tests), while the
# remote hosts it does aim at are all off-box by definition.
_LOOPBACK_HOSTS = ("localhost", "localhost.localdomain", "ip6-localhost")


def _is_loopback(address):
    """True when this address is this machine talking to itself.

    ipaddress does the parsing rather than a prefix match, because a prefix
    match says yes to "127.example.com" — a real remote host that would then
    walk straight through the guard.
    """
    host = address[0] if isinstance(address, tuple) and address else address
    if not isinstance(host, str):
        return False
    host = host.strip("[]").split("%", 1)[0].lower()   # strip v6 brackets/zone
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        parsed = _ipaddress.ip_address(host)
    except ValueError:
        return False
    # ::ffff:127.0.0.1 is loopback; IPv6Address.is_loopback alone says no.
    return bool((parsed.ipv4_mapped if getattr(parsed, "ipv4_mapped", None)
                 else parsed).is_loopback)


# Long enough for a real local git or npm call, short enough that a wedged child
# cannot hold the suite. Nothing legitimate in these tests takes this long.
_DEFAULT_SUBPROCESS_TIMEOUT = 30


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: this test genuinely needs a real socket; do not block it.",
    )


@pytest.fixture(autouse=True)
def _hermetic(request, monkeypatch):
    if request.node.get_closest_marker("allow_network"):
        yield
        return

    real_connect = _socket.socket.connect

    def _blocked_connect(self, address, *a, **kw):
        # AF_UNIX has no address family risk and is how local tooling talks to
        # itself; only IP sockets leave the machine.
        if self.family in (_socket.AF_INET, _socket.AF_INET6) and not _is_loopback(address):
            raise NetworkAccessInTest(
                111,  # ECONNREFUSED, so errno-inspecting callers behave normally
                f"Connection refused by the test suite's hermetic guard: {address!r}. "
                f"Unit tests must not depend on a remote host — the suite's runtime "
                f"and its pass/fail both become someone else's uptime. "
                f"Mock the client, or mark the test @pytest.mark.allow_network if it "
                f"truly needs a socket."
            )
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(_socket.socket, "connect", _blocked_connect, raising=False)

    # Patching socket.connect only covers sockets THIS process opens. The calls
    # that actually cost us were in children: blocked_triage shells out to
    # `git ls-remote --heads origin`, and git opens its own connections, which
    # no amount of monkeypatching here can see.
    #
    # Point children at a proxy on the discard port instead. Nothing listens
    # there, so an outbound connection is refused in microseconds rather than
    # waiting out a 60s timeout — the test still exercises the failure path it
    # was always going to hit offline, it just stops paying GitHub latency to
    # get there. GIT_TERMINAL_PROMPT=0 stops git blocking on a credential prompt
    # when stdin is captured.
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    # ...but never for loopback. urllib in THIS process honours http_proxy too,
    # so an empty no_proxy sent a test's request to its own ephemeral port
    # through the discard-port proxy and got it refused. The proxy exists to
    # short-circuit children reaching REMOTE hosts; exempting the local machine
    # costs it nothing and stops it hijacking in-process loopback calls.
    for var in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(var, "localhost,127.0.0.1,::1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("GIT_ASKPASS", "/usr/bin/false")
    monkeypatch.setenv("SSH_ASKPASS", "/usr/bin/false")

    # db.py retries transient HTTP failures with exponential backoff
    # (time.sleep(min(12, 2**attempt))). Offline, every attempt fails, so a test
    # that reaches an unmocked db path pays the full retry ladder — measured at
    # ~5 seconds per test across this suite, for calls that were never going to
    # succeed. HTTP_RETRIES and HTTP_TIMEOUT are read once at import, so the
    # ORCH_SUPABASE_* env knobs cannot reach them from here; patch the constants.
    #
    # One attempt, short timeout. A test that depends on the retry LADDER should
    # set these itself and say why.
    monkeypatch.setattr(_real_db, "HTTP_RETRIES", 1, raising=False)
    monkeypatch.setattr(_real_db, "HTTP_TIMEOUT", 2.0, raising=False)

    # A subprocess with no timeout can wedge the run forever. runner/ has ~531
    # such call sites; this stops any of them being reached from a test without
    # anyone noticing.
    for name in ("run", "check_output", "call", "check_call"):
        real = getattr(_subprocess, name, None)
        if real is None:
            continue

        def _guard(*a, __real=real, __name=name, **kw):
            # INJECT a bound; do not raise.
            #
            # The first version of this raised on a missing timeout. It fired
            # 1,428 times — runner/ has ~531 such call sites and the tests
            # legitimately exercise them — which turned a suite that had just
            # started finishing into a red one. A guard that makes the suite red
            # on arrival does not get fixed; it gets ignored, and then everything
            # behind it gets ignored too.
            #
            # The actual goal is that no child runs unbounded. Supplying the
            # bound achieves that without failing anyone's test, and the warning
            # leaves a trail for whoever wants to fix the call site properly.
            if kw.get("timeout") is None:
                kw["timeout"] = _DEFAULT_SUBPROCESS_TIMEOUT
                warnings.warn(
                    f"subprocess.{__name}() called with no timeout from a test; "
                    f"bounded to {_DEFAULT_SUBPROCESS_TIMEOUT}s. Pass timeout= at "
                    f"the call site: {(a[0] if a else kw.get('args'))!r}",
                    UnboundedSubprocessInTest,
                    stacklevel=2,
                )
            return __real(*a, **kw)

        monkeypatch.setattr(_subprocess, name, _guard, raising=False)

    yield
