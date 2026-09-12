"""Don't ask a model to fix a rate limit.

build_fixer turns a RED build into a model-generated "name the file and the change"
directive, and that directive is injected into the task note so the NEXT attempt is
steered by it. But not every red build is a code defect: a connection reset, a 429, a
provider overload and an exhausted budget all arrive here as a failed build log. Asked to
name the file that fixes one, a model produces a confident, wrong answer — and the next
attempt is then steered by an explanation of a problem that was never in the code.

runner/error_classifier.py already encodes this taxonomy and had NO callers anywhere in
runner/. This wires it in as the guard.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_fixer  # noqa: E402


class TestClassification:
    @pytest.mark.parametrize("log", [
        "Connection reset by peer: urlopen error errno 104",
        "429 Too Many Requests — rate limit exceeded",
        "provider overloaded, please retry (503)",
    ])
    def test_a_transient_failure_is_not_a_code_defect(self, log):
        category, is_code = build_fixer.classify_build_failure(log)
        assert category == "transient"
        assert is_code is False

    def test_an_exhausted_budget_is_not_a_code_defect(self):
        category, is_code = build_fixer.classify_build_failure("budget cap reached")
        assert category == "resource"
        assert is_code is False

    def test_an_auth_failure_is_not_a_code_defect(self):
        category, is_code = build_fixer.classify_build_failure(
            "permission denied: 403 invalid api key")
        assert category == "permission"
        assert is_code is False

    @pytest.mark.parametrize("log", [
        "src/foo.ts(3,1): error TS2304: Cannot find name 'x'",
        "npm ERR! missing script: build",
        "SyntaxError: invalid syntax",
    ])
    def test_a_real_build_error_is_treated_as_a_code_defect(self, log):
        _category, is_code = build_fixer.classify_build_failure(log)
        assert is_code is True

    def test_an_unrecognised_failure_defaults_to_code_defect(self):
        """Suppressing the directive on a REAL break is the more expensive mistake."""
        category, is_code = build_fixer.classify_build_failure("something nobody has seen")
        assert is_code is True
        assert category == "unknown"

    @pytest.mark.parametrize("log", [None, "", 7, []])
    def test_it_never_raises(self, log):
        category, is_code = build_fixer.classify_build_failure(log)
        assert isinstance(category, str)
        assert is_code in (True, False)

    def test_it_is_fail_soft_when_the_classifier_is_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "error_classifier", None)
        category, is_code = build_fixer.classify_build_failure("connection reset")
        assert (category, is_code) == ("unknown", True)


class TestModelCallIsSkipped:
    def _no_model(self, monkeypatch):
        def _boom(*_a, **_k):
            raise AssertionError("a model call was made for a non-code failure")
        monkeypatch.setattr(build_fixer, "_pick_fixer", _boom)

    @pytest.mark.parametrize("log", [
        "Connection reset by peer: urlopen errno 104",
        "429 Too Many Requests — rate limit exceeded",
        "budget cap reached",
        "permission denied: 403 invalid api key",
    ])
    def test_no_model_is_asked_about_a_non_code_failure(self, monkeypatch, log):
        self._no_model(monkeypatch)
        assert build_fixer.fix_directive(log) == ""

    def test_a_real_build_error_still_reaches_the_model(self, monkeypatch):
        """The guard must not swallow the case build_fixer exists for."""
        import types
        reached = {}

        def _pick():
            reached["picked"] = True
            return ("google", "m")

        monkeypatch.setattr(build_fixer, "_pick_fixer", _pick)
        # Stub the gateway too: this asserts the guard lets the call THROUGH, and must not
        # actually reach a provider to do it.
        monkeypatch.setitem(sys.modules, "model_gateway", types.SimpleNamespace(
            complete=lambda *_a, **_k: {"text": "fix foo.ts", "provider": "google",
                                        "model": "m"}))
        out = build_fixer.fix_directive("src/foo.ts(3,1): error TS2304: Cannot find name 'x'")
        assert reached.get("picked") is True
        assert "fix foo.ts" in out

    def test_an_empty_log_is_still_a_no_op(self, monkeypatch):
        self._no_model(monkeypatch)
        assert build_fixer.fix_directive("") == ""
        assert build_fixer.fix_directive(None) == ""

    def test_the_kill_switch_still_wins(self, monkeypatch):
        monkeypatch.setenv("ORCH_BUILD_FIXER", "false")
        self._no_model(monkeypatch)
        assert build_fixer.fix_directive("error TS2304") == ""


class TestTaxonomyIsShared:
    def test_the_categories_come_from_error_classifier(self):
        """One taxonomy, not a second private copy that drifts."""
        import error_classifier
        for name in build_fixer.NON_CODE_CATEGORIES:
            assert name in (error_classifier.TRANSIENT, error_classifier.RESOURCE,
                            error_classifier.PERMISSION)

    def test_code_shaped_categories_are_not_suppressed(self):
        import error_classifier
        for category in (error_classifier.TOOLCHAIN, error_classifier.CONFLICT,
                         error_classifier.LOGIC, error_classifier.MODEL):
            assert category not in build_fixer.NON_CODE_CATEGORIES
