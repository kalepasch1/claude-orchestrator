import logging
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import log_util


def _reset():
    """Reset module state between tests that modify global setup."""
    log_util._configured = False
    # Remove any handlers added by basicConfig to avoid cross-test bleed.
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)


class TestGetLogger(unittest.TestCase):
    def test_returns_logger_instance(self):
        logger = log_util.get_logger("test.module")
        self.assertIsInstance(logger, logging.Logger)

    def test_name_is_set(self):
        logger = log_util.get_logger("my.module")
        self.assertEqual(logger.name, "my.module")

    def test_different_names_return_different_loggers(self):
        a = log_util.get_logger("module.a")
        b = log_util.get_logger("module.b")
        self.assertIsNot(a, b)
        self.assertNotEqual(a.name, b.name)

    def test_same_name_returns_same_logger(self):
        a = log_util.get_logger("module.same")
        b = log_util.get_logger("module.same")
        self.assertIs(a, b)

    def test_empty_string_falls_back_to_module_name(self):
        logger = log_util.get_logger("")
        self.assertIsNotNone(logger)
        self.assertIsInstance(logger, logging.Logger)

    def test_dunder_name_pattern(self):
        logger = log_util.get_logger("runner.fleet_control")
        self.assertEqual(logger.name, "runner.fleet_control")

    def test_nested_module_name(self):
        logger = log_util.get_logger("runner.tests.something.deep")
        self.assertEqual(logger.name, "runner.tests.something.deep")

    def test_logger_can_emit_warning(self):
        logger = log_util.get_logger("test.emit.warning")
        with self.assertLogs(logger, level="WARNING") as cm:
            logger.warning("fleet_config load failed: %s", "timeout")
        self.assertIn("fleet_config load failed: timeout", cm.output[0])

    def test_logger_can_emit_error(self):
        logger = log_util.get_logger("test.emit.error")
        with self.assertLogs(logger, level="ERROR") as cm:
            logger.error("critical failure: %s", "db down")
        self.assertIn("critical failure: db down", cm.output[0])

    def test_logger_can_emit_debug(self):
        logger = log_util.get_logger("test.emit.debug")
        with self.assertLogs(logger, level="DEBUG") as cm:
            logger.debug("debug info: %s", "value=42")
        self.assertIn("debug info: value=42", cm.output[0])

    def test_logger_can_emit_info(self):
        logger = log_util.get_logger("test.emit.info")
        with self.assertLogs(logger, level="INFO") as cm:
            logger.info("info message")
        self.assertIn("info message", cm.output[0])

    def test_logger_can_emit_critical(self):
        logger = log_util.get_logger("test.emit.critical")
        with self.assertLogs(logger, level="CRITICAL") as cm:
            logger.critical("system failure")
        self.assertIn("system failure", cm.output[0])

    def test_format_includes_level_and_name(self):
        logger = log_util.get_logger("test.format.check")
        with self.assertLogs(logger, level="WARNING") as cm:
            logger.warning("format probe")
        record = cm.output[0]
        self.assertIn("WARNING", record)
        self.assertIn("test.format.check", record)


class TestSetupLogging(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_setup_logging_is_idempotent(self):
        log_util.setup_logging()
        log_util.setup_logging()
        log_util.setup_logging()
        self.assertTrue(log_util._configured)

    def test_configured_flag_set_after_first_call(self):
        self.assertFalse(log_util._configured)
        log_util.setup_logging()
        self.assertTrue(log_util._configured)

    def test_default_level_is_warning_without_env(self):
        os.environ.pop("ORCH_LOG_LEVEL", None)
        log_util.setup_logging()
        self.assertEqual(logging.getLogger().level, logging.WARNING)

    def test_level_from_env_var_debug(self):
        os.environ["ORCH_LOG_LEVEL"] = "DEBUG"
        try:
            log_util.setup_logging()
            self.assertEqual(logging.getLogger().level, logging.DEBUG)
        finally:
            os.environ.pop("ORCH_LOG_LEVEL", None)

    def test_level_from_env_var_info(self):
        os.environ["ORCH_LOG_LEVEL"] = "INFO"
        try:
            log_util.setup_logging()
            self.assertEqual(logging.getLogger().level, logging.INFO)
        finally:
            os.environ.pop("ORCH_LOG_LEVEL", None)

    def test_level_from_env_var_error(self):
        os.environ["ORCH_LOG_LEVEL"] = "ERROR"
        try:
            log_util.setup_logging()
            self.assertEqual(logging.getLogger().level, logging.ERROR)
        finally:
            os.environ.pop("ORCH_LOG_LEVEL", None)

    def test_invalid_env_level_falls_back_to_warning(self):
        os.environ["ORCH_LOG_LEVEL"] = "NOTAREAL"
        try:
            log_util.setup_logging()
            self.assertEqual(logging.getLogger().level, logging.WARNING)
        finally:
            os.environ.pop("ORCH_LOG_LEVEL", None)

    def test_env_var_case_insensitive(self):
        os.environ["ORCH_LOG_LEVEL"] = "debug"
        try:
            log_util.setup_logging()
            self.assertEqual(logging.getLogger().level, logging.DEBUG)
        finally:
            os.environ.pop("ORCH_LOG_LEVEL", None)


class TestThreadSafety(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_concurrent_setup_logging_calls_are_safe(self):
        errors = []

        def call_setup():
            try:
                log_util.setup_logging()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_setup) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertTrue(log_util._configured)

    def test_concurrent_get_logger_calls_are_safe(self):
        errors = []
        loggers = []
        lock = threading.Lock()

        def call_get():
            try:
                logger = log_util.get_logger("concurrent.test")
                with lock:
                    loggers.append(logger)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_get) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(loggers), 20)
        # All should be the same logger object
        self.assertTrue(all(lg is loggers[0] for lg in loggers))


if __name__ == "__main__":
    unittest.main()
