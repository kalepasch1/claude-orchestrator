#!/usr/bin/env python3
"""
test_darwin_determinations.py - test suite for the darwin_determinations module.

Tests cover:
  1. Mock path with all env vars unset (default behavior)
  2. Live path: model selection, credential handling, empty responses
  3. Fallback to mock on every failure mode (missing SDK, bad key, network error)
  4. Error logging
  5. Backwards compatibility (public signature unchanged)

WHY THE ANTHROPIC SDK IS FAKED THE WAY IT IS
--------------------------------------------
Every live-path test here used to do `patch("anthropic.Anthropic", ...)`. mock.patch
resolves its target by IMPORTING it, and the anthropic SDK is not installed in this
environment, so all fifteen of those tests died at patch time with
`ModuleNotFoundError: No module named 'anthropic'` -- before reaching a single assertion.
The tests were not describing a product bug; they were describing an SDK that was never
there.

`_live_determine` does `from anthropic import Anthropic` INSIDE the call, so a module
object placed in sys.modules for the duration of a test is exactly what the import
machinery hands it. `patch.dict(sys.modules, ...)` installs and removes that object with
no residue, and lets the fake constructor record the kwargs the product actually passes --
so these tests now assert something the old ones only claimed in a comment (that
DARWIN_API_KEY reaches the client).

REACHABILITY. Nothing in the fleet imports darwin_determinations: it has no entry in
runner._SCHEDULE, no periodic.JOBS job, and no importer other than this file. It is a
standalone module, and these tests are its only exercise.
"""
import builtins
import contextlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# runner/ appended rather than inserted at 0: at sys.path[0] the module file
# runner/runner.py shadows the runner/ package for the rest of the session (see the
# repo-root conftest.py).
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import darwin_determinations  # noqa: E402


_DARWIN_ENV = ("DARWIN_LIVE", "DARWIN_API_KEY", "DARWIN_MODEL", "ANTHROPIC_API_KEY")


def _message(text="LIVE_RESULT"):
    """An SDK response object shaped like anthropic's Message: .content[0].text."""
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


class RecordingAnthropic:
    """Stand-in for anthropic.Anthropic that records how it was constructed and called."""

    def __init__(self, response=None, create_error=None, init_error=None):
        self.response = response if response is not None else _message()
        self.create_error = create_error
        self.init_error = init_error
        self.init_kwargs = None
        self.create_kwargs = None

    def __call__(self, **kwargs):
        """Constructing the client."""
        if self.init_error is not None:
            raise self.init_error
        self.init_kwargs = kwargs
        client = types.SimpleNamespace()
        client.messages = types.SimpleNamespace(create=self._create)
        return client

    def _create(self, **kwargs):
        self.create_kwargs = kwargs
        if self.create_error is not None:
            raise self.create_error
        return self.response


@contextlib.contextmanager
def fake_sdk(**kwargs):
    """Install a fake `anthropic` package for the body of the with-block.

    `_live_determine` imports the SDK lazily, so putting a module object in sys.modules is
    all it takes. patch.dict removes it again on exit -- nothing is left behind.
    """
    factory = RecordingAnthropic(**kwargs)
    module = types.ModuleType("anthropic")
    module.Anthropic = factory
    with patch.dict(sys.modules, {"anthropic": module}):
        yield factory


@contextlib.contextmanager
def no_sdk():
    """Make `from anthropic import Anthropic` fail, whether or not the SDK is installed.

    A None entry in sys.modules is the documented way to force an ImportError, so this
    test does not silently become a no-op the day someone `pip install anthropic`s.
    """
    with patch.dict(sys.modules, {"anthropic": None}):
        yield


class DarwinTestCase(unittest.TestCase):
    """Clears the DARWIN_* env vars for each test and restores the environment after."""

    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in _DARWIN_ENV:
            os.environ.pop(key, None)


class TestDarwinDeterminationsMock(DarwinTestCase):
    """Test cases for mock (default) path."""

    def test_mock_path_default(self):
        """DARWIN_LIVE unset -> mock path, deterministic result."""
        self.assertEqual(darwin_determinations.determine(), "MOCK_DETERMINATION_RESULT")

    def test_mock_path_live_disabled_explicitly(self):
        """DARWIN_LIVE=0 -> mock path (flag is off)."""
        os.environ["DARWIN_LIVE"] = "0"
        self.assertEqual(darwin_determinations.determine(), "MOCK_DETERMINATION_RESULT")

    def test_mock_path_does_not_touch_the_sdk(self):
        """The default path must not import or call the SDK at all -- if it did, every
        deployment without the anthropic package would be logging errors on every call."""
        os.environ["DARWIN_API_KEY"] = "unused"
        with no_sdk(), patch.object(darwin_determinations, "log") as mock_log:
            self.assertEqual(darwin_determinations.determine(), "MOCK_DETERMINATION_RESULT")
        mock_log.error.assert_not_called()

    def test_mock_path_live_with_trailing_whitespace(self):
        """DARWIN_LIVE='1  ' -> live path is enabled (whitespace is stripped)."""
        os.environ["DARWIN_LIVE"] = "1  "
        with patch.object(darwin_determinations, "_live_determine",
                          return_value="LIVE_RESULT") as mock_live:
            result = darwin_determinations.determine()
        mock_live.assert_called_once()
        self.assertEqual(result, "LIVE_RESULT")

    def test_unrecognised_live_value_stays_on_the_mock_path(self):
        """Only "1" enables the live path; anything else is off, fail-closed."""
        for value in ("true", "yes", "2", ""):
            with self.subTest(value=value):
                os.environ["DARWIN_LIVE"] = value
                with patch.object(darwin_determinations, "_live_determine") as mock_live:
                    result = darwin_determinations.determine()
                mock_live.assert_not_called()
                self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_backwards_compatibility_no_args(self):
        """determine() takes no required arguments."""
        result = darwin_determinations.determine()
        self.assertIsInstance(result, str)

    def test_mock_determine_direct(self):
        """_mock_determine() returns the deterministic result."""
        self.assertEqual(darwin_determinations._mock_determine(), "MOCK_DETERMINATION_RESULT")


class TestDarwinDeterminationsLive(DarwinTestCase):
    """Test cases for live model path."""

    def test_live_path_with_valid_key(self):
        """DARWIN_LIVE=1 with a key -> live call, and the key reaches the client.

        The old version of this test asserted only that create() was called; the comment
        claimed it verified the API key, which nothing in it did. The fake constructor
        records its kwargs, so the claim is now an assertion.
        """
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        with fake_sdk() as sdk:
            result = darwin_determinations.determine()

        self.assertEqual(result, "LIVE_RESULT")
        self.assertEqual(sdk.init_kwargs, {"api_key": "valid_key"})
        self.assertIsNotNone(sdk.create_kwargs)

    def test_live_path_with_custom_model(self):
        """DARWIN_MODEL is forwarded to the API call."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"
        os.environ["DARWIN_MODEL"] = "custom-model-id"

        with fake_sdk() as sdk:
            darwin_determinations.determine()

        self.assertEqual(sdk.create_kwargs["model"], "custom-model-id")

    def test_live_path_without_api_key(self):
        """No DARWIN_API_KEY -> client constructed with no explicit key (ambient creds)."""
        os.environ["DARWIN_LIVE"] = "1"

        with fake_sdk() as sdk:
            result = darwin_determinations.determine()

        self.assertEqual(result, "LIVE_RESULT")
        self.assertEqual(sdk.init_kwargs, {})

    def test_live_path_with_invalid_key_fallback(self):
        """A client that refuses to construct -> mock result, one logged error."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid_key"

        with fake_sdk(init_error=Exception("Invalid API key")):
            with patch.object(darwin_determinations, "log") as mock_log:
                result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
        mock_log.error.assert_called_once()
        fmt = mock_log.error.call_args[0][0]
        self.assertIn("[DARWIN]", fmt)
        self.assertIn("falling back to mock", fmt)

    def test_live_path_with_default_model(self):
        """DARWIN_MODEL unset -> DEFAULT_MODEL is used."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        with fake_sdk() as sdk:
            darwin_determinations.determine()

        self.assertEqual(sdk.create_kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(sdk.create_kwargs["model"], darwin_determinations.DEFAULT_MODEL)

    def test_live_call_is_bounded(self):
        """The determination call asks for one short completion, not an open-ended one."""
        os.environ["DARWIN_LIVE"] = "1"

        with fake_sdk() as sdk:
            darwin_determinations.determine()

        self.assertEqual(sdk.create_kwargs["max_tokens"], 100)
        self.assertEqual([m["role"] for m in sdk.create_kwargs["messages"]], ["user"])

    def test_live_path_empty_response(self):
        """Empty content -> LIVE_DETERMINATION_EMPTY (distinct from the mock result, so a
        caller can tell 'the model said nothing' from 'the live path never ran')."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        empty = MagicMock()
        empty.content = []
        with fake_sdk(response=empty):
            result = darwin_determinations.determine()

        self.assertEqual(result, "LIVE_DETERMINATION_EMPTY")

    def test_live_path_import_error(self):
        """SDK not installed -> mock fallback, error logged."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        with no_sdk():
            with patch.object(darwin_determinations, "log") as mock_log:
                result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
        mock_log.error.assert_called_once()
        # The blocked import surfaces as ModuleNotFoundError, an ImportError subclass;
        # what matters is that the log names the failing dependency.
        exc_type, exc_msg = mock_log.error.call_args[0][1:]
        self.assertTrue(issubclass(getattr(builtins, exc_type), ImportError))
        self.assertIn("anthropic", exc_msg)

    def test_live_path_network_error(self):
        """A failing API call -> mock fallback, error logged."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "valid_key"

        with fake_sdk(create_error=RuntimeError("Connection timeout")):
            with patch.object(darwin_determinations, "log") as mock_log:
                result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
        mock_log.error.assert_called_once()

    def test_live_determine_honours_an_explicit_model_argument(self):
        """_live_determine(model=...) beats DARWIN_MODEL -- the parameter exists for the
        caller that already resolved the model, which is what determine() is."""
        os.environ["DARWIN_MODEL"] = "env-model"

        with fake_sdk() as sdk:
            darwin_determinations._live_determine(model="explicit-model")

        self.assertEqual(sdk.create_kwargs["model"], "explicit-model")

    def test_live_determine_falls_back_to_the_env_model(self):
        os.environ["DARWIN_MODEL"] = "env-model"

        with fake_sdk() as sdk:
            darwin_determinations._live_determine()

        self.assertEqual(sdk.create_kwargs["model"], "env-model")


class TestDarwinDeterminationsTruthTable(DarwinTestCase):
    """The env var truth table from the module docstring, row by row."""

    def test_truth_table_unset_unset_unset(self):
        """Row 1: all unset -> mock path."""
        self.assertEqual(darwin_determinations.determine(), "MOCK_DETERMINATION_RESULT")

    def test_truth_table_0_any_any(self):
        """Row 2: DARWIN_LIVE=0 with key and model set -> mock path (flag wins)."""
        os.environ["DARWIN_LIVE"] = "0"
        os.environ["DARWIN_API_KEY"] = "dummy_key"
        os.environ["DARWIN_MODEL"] = "dummy_model"
        self.assertEqual(darwin_determinations.determine(), "MOCK_DETERMINATION_RESULT")

    def test_truth_table_1_valid_key_unset(self):
        """Row 3: live + key, no model -> live call on the default model."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "sk-valid-key"

        with fake_sdk() as sdk:
            result = darwin_determinations.determine()

        self.assertEqual(result, "LIVE_RESULT")
        self.assertEqual(sdk.create_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_truth_table_1_valid_key_custom_model(self):
        """Row 4: live + key + model -> live call on the custom model."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "sk-valid-key"
        os.environ["DARWIN_MODEL"] = "custom-model-id"

        with fake_sdk() as sdk:
            darwin_determinations.determine()

        self.assertEqual(sdk.create_kwargs["model"], "custom-model-id")

    def test_truth_table_1_unset_any(self):
        """Row 5: live, no key -> ambient credentials.

        The old version ended in a bare `pass` with a comment saying the constructor args
        could not be checked. With a fake constructor they can be, so the row is now
        actually verified.
        """
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_MODEL"] = "any-model"

        with fake_sdk() as sdk:
            result = darwin_determinations.determine()

        self.assertEqual(result, "LIVE_RESULT")
        self.assertEqual(sdk.init_kwargs, {})

    def test_truth_table_1_invalid_key_any(self):
        """Row 6: live + bad key -> caught, mock fallback, logged."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid_key"

        with fake_sdk(init_error=Exception("Invalid key")):
            with patch.object(darwin_determinations, "log") as mock_log:
                result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")
        mock_log.error.assert_called_once()
        self.assertIn("[DARWIN]", str(mock_log.error.call_args))


class TestDarwinDeterminationsIntegration(DarwinTestCase):
    """Integration tests."""

    def test_integration_fallback_on_missing_module(self):
        """Missing anthropic module -> fallback works end to end."""
        os.environ["DARWIN_LIVE"] = "1"

        with no_sdk(), patch.object(darwin_determinations, "log"):
            result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_integration_multiple_calls_consistent(self):
        """Repeated calls with the same config agree."""
        result1 = darwin_determinations.determine()
        result2 = darwin_determinations.determine()
        self.assertEqual(result1, result2)
        self.assertEqual(result1, "MOCK_DETERMINATION_RESULT")

    def test_integration_live_to_mock_fallback(self):
        """Live path failure degrades to the mock result rather than raising."""
        os.environ["DARWIN_LIVE"] = "1"

        with fake_sdk(create_error=RuntimeError("API Error")):
            with patch.object(darwin_determinations, "log"):
                result = darwin_determinations.determine()

        self.assertEqual(result, "MOCK_DETERMINATION_RESULT")

    def test_a_failed_live_call_does_not_poison_the_next_one(self):
        """No state is carried between calls: a recovered SDK is used immediately."""
        os.environ["DARWIN_LIVE"] = "1"

        with fake_sdk(create_error=RuntimeError("blip")):
            with patch.object(darwin_determinations, "log"):
                first = darwin_determinations.determine()
        with fake_sdk():
            second = darwin_determinations.determine()

        self.assertEqual(first, "MOCK_DETERMINATION_RESULT")
        self.assertEqual(second, "LIVE_RESULT")


class TestDarwinDeterminationsLogging(DarwinTestCase):
    """Test logging behavior."""

    def test_error_logging_format(self):
        """The error log carries the exception type and message as lazy args."""
        os.environ["DARWIN_LIVE"] = "1"
        os.environ["DARWIN_API_KEY"] = "invalid"

        with fake_sdk(init_error=ValueError("Bad value")):
            with patch.object(darwin_determinations, "log") as mock_log:
                darwin_determinations.determine()

        mock_log.error.assert_called_once()
        fmt, *args = mock_log.error.call_args[0]
        self.assertIn("[DARWIN]", fmt)
        self.assertIn("falling back to mock", fmt)
        self.assertEqual(args, ["ValueError", "Bad value"])

    def test_no_logging_on_mock_path(self):
        """The mock path logs nothing at all.

        WAS: `mock_log.assert_not_called()`, which asserts the module object itself was
        never CALLED -- true of any logger, whatever it logged. Assert on the methods.
        """
        with patch.object(darwin_determinations, "log") as mock_log:
            darwin_determinations.determine()

        mock_log.error.assert_not_called()
        mock_log.warning.assert_not_called()
        mock_log.exception.assert_not_called()


if __name__ == "__main__":
    unittest.main()
