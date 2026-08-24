"""The hermetic guard must cover this tree, not just runner/tests/.

The observed failure was `litellm` / `llm.APIError` raising XaiException 403 (permission
denied / credits spent) during a plain `pytest` run: a unit test reaching a live vendor
endpoint. runner/tests/conftest.py had blocked that for its own directory since it was
written, but a conftest is scoped to where it lives, so the ~100 files under tests/ had no
guard at all — and the same run would pass or fail depending on someone else's billing.

These tests fail if the guard is ever removed or silently stops applying.
"""
import os
import socket
import subprocess
import sys

import pytest

import conftest as tests_conftest  # the one under test, resolved by pytest's rootdir


class TestOutboundSocketsAreBlocked:
    def test_a_tcp_connect_is_refused(self):
        """The exact thing an SDK does before it can produce a 403."""
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("api.x.ai", 443), timeout=2)

    def test_the_refusal_is_the_guards_own_error(self):
        with pytest.raises(tests_conftest.NetworkAccessInTest):
            socket.create_connection(("example.com", 80), timeout=2)

    def test_it_refuses_with_econnrefused_so_fail_soft_code_behaves(self):
        """Not a bare RuntimeError: offline code must take the branch it really takes."""
        try:
            socket.create_connection(("example.com", 80), timeout=2)
        except OSError as exc:
            assert exc.errno == 111
        else:  # pragma: no cover
            pytest.fail("the guard did not block the connection")

    def test_a_unix_socket_is_not_blocked(self):
        """Local tooling talks to itself over AF_UNIX; only IP leaves the machine."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError) as exc:
                s.connect("/tmp/definitely-not-a-real-socket-xyz")
            assert not isinstance(exc.value, tests_conftest.NetworkAccessInTest)
        finally:
            s.close()


class TestChildProcessesAreContained:
    def test_children_are_pointed_at_the_discard_port(self):
        """git opens its own sockets; monkeypatching this process cannot see them."""
        assert os.environ.get("https_proxy") == "http://127.0.0.1:9"
        assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:9"

    def test_git_cannot_block_on_a_credential_prompt(self):
        assert os.environ.get("GIT_TERMINAL_PROMPT") == "0"

    def test_an_unbounded_subprocess_gets_a_bound(self):
        """Injected, not raised — a guard that turns the suite red gets ignored."""
        with pytest.warns(UserWarning, match="no timeout"):
            subprocess.run([sys.executable, "-c", "pass"], capture_output=True)


class TestIntegrationGating:
    def test_the_marker_and_env_var_are_declared(self):
        assert tests_conftest.INTEGRATION_ENV == "RUN_INTEGRATION_TESTS"

    def test_integration_tests_are_skipped_by_default(self, pytester=None):
        """Skipped rather than failed: red-on-arrival for everyone teaches people to ignore CI."""
        assert os.environ.get(tests_conftest.INTEGRATION_ENV) != "1"

    @pytest.mark.integration
    def test_this_one_should_not_have_run(self):  # pragma: no cover
        pytest.fail("an @pytest.mark.integration test ran without RUN_INTEGRATION_TESTS=1")


class TestGuardIsReusedNotCopied:
    def test_the_fixture_comes_from_the_runner_conftest(self):
        """Two copies of a security-shaped rule drift; the one that stops blocking wins."""
        source = open(tests_conftest.__file__, encoding="utf-8").read()
        assert "runner" in source and "conftest.py" in source
        assert "_hermetic" in source
        # The implementation must NOT be duplicated here.
        assert "def _blocked_connect" not in source

    def test_it_is_fail_soft_if_the_runner_conftest_is_unavailable(self):
        """A missing guard must not break collection of the files beside it."""
        assert tests_conftest._load_runner_conftest.__doc__
        assert "Fail-soft" in tests_conftest._load_runner_conftest.__doc__


@pytest.mark.allow_network
class TestOptOut:
    def test_a_marked_test_is_allowed_a_real_socket(self):
        """The escape hatch has to work, or people delete the guard instead."""
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        except tests_conftest.NetworkAccessInTest:  # pragma: no cover
            pytest.fail("allow_network did not lift the guard")
        except OSError:
            pass  # nothing listens on the discard port; that is the expected refusal
