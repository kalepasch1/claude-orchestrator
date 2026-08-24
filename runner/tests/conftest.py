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
        if getattr(module, "__file__", None):
            continue
        if not os.path.isfile(os.path.join(_RUNNER_DIR, f"{name}.py")):
            continue
        real = _REAL_MODULES.get(name)
        if real is not None:
            sys.modules[name] = real
        else:
            del sys.modules[name]


def _restore_real_modules():
    _remember_real_modules()
    sys.modules.update(_REAL_MODULES)
    _evict_stub_shadows()


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makemodule(module_path, parent):
    """Prevent synthetic control-plane modules from leaking into later modules."""
    yield
    _restore_real_modules()


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


# Long enough for a real local git or npm call, short enough that a wedged child
# cannot hold the suite. Nothing legitimate in these tests takes this long.
_DEFAULT_SUBPROCESS_TIMEOUT = 30


_LOOPBACK_HOSTS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost",
                             "::1", "::ffff:127.0.0.1", "0:0:0:0:0:0:0:1"})


def _is_loopback(address):
    """True when `address` names this machine and the packets never leave it.

    Accepts the (host, port[, flowinfo, scope_id]) tuples socket.connect is given.
    Deliberately conservative: anything it cannot positively identify as loopback is
    treated as remote and blocked, so a widened guard can never silently let real
    egress through. It does NOT resolve names — a DNS lookup here would be exactly
    the remote dependency the guard exists to prevent — so only the literal loopback
    spellings above and the 127.0.0.0/8 block are recognised.
    """
    try:
        host = address[0] if isinstance(address, (tuple, list)) else address
    except Exception:
        return False
    if not isinstance(host, (str, bytes, bytearray)):
        return False
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("ascii")
        except Exception:
            return False
    host = host.strip().strip("[]").lower()
    if host in _LOOPBACK_HOSTS:
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return parts[0] == "127"
    return False


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
        #
        # LOOPBACK IS NOT THE NETWORK. The guard's own rationale is "the suite's
        # runtime and its pass/fail become someone else's uptime" — nobody else's
        # uptime is involved in 127.0.0.1. Blocking it anyway broke tests that talk
        # to a server THIS PROCESS started: runner/tests/test_canary_metrics_server.py
        # binds the canary /metrics endpoint on localhost and then scrapes it, which
        # is exactly the behaviour under test, and five of its cases failed with
        # "Connection refused by the test suite's hermetic guard". Marking them
        # @allow_network would have been the wrong fix: it would also re-open real
        # egress for those tests, to work around a rule that should never have
        # applied to them.
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

    def _blocked_connect_ex(self, address, *a, **kw):
        """connect_ex is the same egress, spelled so it returns errno instead of raising.

        The guard only ever wrapped `connect`, so any caller that used `connect_ex`
        went straight out to the real network — a port scanner, a health probe, or
        `socket.socket().connect_ex(("example.com", 80))` in a test all bypassed it
        silently. Silently is the problem: a hole that raises nothing looks exactly
        like a suite with no remote dependencies.

        Returns ECONNREFUSED rather than raising, because that is connect_ex's whole
        contract — a caller that gets an exception here would break on the guard in a
        way it would never break offline.
        """
        if self.family in (_socket.AF_INET, _socket.AF_INET6) and not _is_loopback(address):
            return 111  # ECONNREFUSED
        return real_connect_ex(self, address, *a, **kw)

    real_connect_ex = _socket.socket.connect_ex

    monkeypatch.setattr(_socket.socket, "connect", _blocked_connect, raising=False)
    monkeypatch.setattr(_socket.socket, "connect_ex", _blocked_connect_ex, raising=False)

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
    # ...but loopback must bypass that proxy. Emptying no_proxy sent even
    # http://127.0.0.1:<port>/metrics through the dead discard-port proxy, so a test
    # scraping its OWN in-process server was refused by the guard's plumbing rather
    # than by the guard's rule. Exempting loopback keeps every remote destination
    # proxied into the void exactly as before.
    _LOOPBACK_NO_PROXY = "localhost,127.0.0.1,::1"
    monkeypatch.setenv("no_proxy", _LOOPBACK_NO_PROXY)
    monkeypatch.setenv("NO_PROXY", _LOOPBACK_NO_PROXY)
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
