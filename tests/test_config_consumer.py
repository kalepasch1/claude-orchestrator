"""Tests for beethoven.config_consumer — typed fail-soft YAML config loader."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from beethoven import config_consumer
from beethoven.config_consumer import OrchestrationConfig, load_orchestration_config


def write_config(tmp_path, content):
    path = tmp_path / "orchestration.yaml"
    path.write_text(content, encoding="utf-8")
    return path


FULL_CONFIG = """
max_parallel_tasks: 8
poll_interval_seconds: 2.5
retry_limit: 5
task_timeout_seconds: 120
log_level: DEBUG
queue_name: fleet
fail_fast: true
"""


# ---------------------------------------------------------------- happy paths

def test_full_config_loads_all_keys(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, FULL_CONFIG))
    assert cfg == OrchestrationConfig(
        max_parallel_tasks=8,
        poll_interval_seconds=2.5,
        retry_limit=5,
        task_timeout_seconds=120,
        log_level="DEBUG",
        queue_name="fleet",
        fail_fast=True,
    )


def test_minimal_config_fills_defaults(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "retry_limit: 9\n"))
    assert cfg.retry_limit == 9
    assert cfg.max_parallel_tasks == config_consumer.DEFAULT_MAX_PARALLEL_TASKS
    assert cfg.log_level == config_consumer.DEFAULT_LOG_LEVEL


def test_accepts_str_path(tmp_path):
    path = write_config(tmp_path, "queue_name: strpath\n")
    assert load_orchestration_config(str(path)).queue_name == "strpath"


def test_int_accepted_for_float_field(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "poll_interval_seconds: 3\n"))
    assert cfg.poll_interval_seconds == 3.0
    assert isinstance(cfg.poll_interval_seconds, float)


def test_numeric_string_coerced_to_int(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, 'retry_limit: "7"\n'))
    assert cfg.retry_limit == 7


def test_string_bool_variants(tmp_path):
    assert load_orchestration_config(write_config(tmp_path, 'fail_fast: "yes"\n')).fail_fast is True
    assert load_orchestration_config(write_config(tmp_path, 'fail_fast: "off"\n')).fail_fast is False


def test_log_level_whitespace_stripped(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, 'log_level: "  WARN  "\n'))
    assert cfg.log_level == "WARN"


def test_to_dict_round_trip(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, FULL_CONFIG))
    d = cfg.to_dict()
    assert d["max_parallel_tasks"] == 8
    assert OrchestrationConfig(**d) == cfg


# ------------------------------------------------------------- fail-soft I/O

def test_missing_file_returns_defaults(tmp_path):
    cfg = load_orchestration_config(tmp_path / "nope.yaml")
    assert cfg == OrchestrationConfig()


def test_none_path_without_env_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv(config_consumer.ENV_CONFIG_PATH, raising=False)
    monkeypatch.chdir(tmp_path)  # no orchestration.yaml here
    assert load_orchestration_config(None) == OrchestrationConfig()


def test_path_is_directory_returns_defaults(tmp_path):
    assert load_orchestration_config(tmp_path) == OrchestrationConfig()


def test_empty_file_returns_defaults(tmp_path):
    assert load_orchestration_config(write_config(tmp_path, "")) == OrchestrationConfig()


def test_malformed_yaml_returns_defaults(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "retry_limit: [unclosed\n  {bad"))
    assert cfg == OrchestrationConfig()


def test_yaml_list_document_returns_defaults(tmp_path):
    assert load_orchestration_config(write_config(tmp_path, "- a\n- b\n")) == OrchestrationConfig()


def test_yaml_scalar_document_returns_defaults(tmp_path):
    assert load_orchestration_config(write_config(tmp_path, "just a string\n")) == OrchestrationConfig()


def test_oversized_file_returns_defaults(tmp_path):
    path = tmp_path / "orchestration.yaml"
    path.write_text("# " + "x" * (config_consumer.MAX_CONFIG_BYTES + 10), encoding="utf-8")
    assert load_orchestration_config(path) == OrchestrationConfig()


def test_unreadable_file_returns_defaults(tmp_path):
    path = write_config(tmp_path, "retry_limit: 5\n")
    path.chmod(0o000)
    try:
        assert load_orchestration_config(path) == OrchestrationConfig()
    finally:
        path.chmod(0o644)


def test_missing_pyyaml_returns_defaults(tmp_path, monkeypatch):
    import builtins
    path = write_config(tmp_path, "retry_limit: 9\n")
    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_yaml)
    assert load_orchestration_config(path) == OrchestrationConfig()


def test_never_raises_on_weird_path_types():
    assert load_orchestration_config(12345) == OrchestrationConfig()
    assert load_orchestration_config(b"\x00bad") == OrchestrationConfig()


# ---------------------------------------------------- per-key type fallbacks

def test_wrong_typed_int_falls_back_per_key(tmp_path):
    cfg = load_orchestration_config(
        write_config(tmp_path, "max_parallel_tasks: not-a-number\nretry_limit: 6\n"))
    assert cfg.max_parallel_tasks == config_consumer.DEFAULT_MAX_PARALLEL_TASKS
    assert cfg.retry_limit == 6


def test_bool_rejected_for_int_field(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "retry_limit: true\n"))
    assert cfg.retry_limit == config_consumer.DEFAULT_RETRY_LIMIT


def test_wrong_typed_float_falls_back(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "poll_interval_seconds: [1, 2]\n"))
    assert cfg.poll_interval_seconds == config_consumer.DEFAULT_POLL_INTERVAL_SECONDS


def test_non_string_log_level_falls_back(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, "log_level: 42\n"))
    assert cfg.log_level == config_consumer.DEFAULT_LOG_LEVEL


def test_empty_string_value_falls_back(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, 'queue_name: ""\n'))
    assert cfg.queue_name == config_consumer.DEFAULT_QUEUE_NAME


def test_null_values_fall_back(tmp_path):
    cfg = load_orchestration_config(
        write_config(tmp_path, "retry_limit: null\nfail_fast: null\n"))
    assert cfg.retry_limit == config_consumer.DEFAULT_RETRY_LIMIT
    assert cfg.fail_fast == config_consumer.DEFAULT_FAIL_FAST


def test_unrecognized_bool_string_falls_back(tmp_path):
    cfg = load_orchestration_config(write_config(tmp_path, 'fail_fast: "maybe"\n'))
    assert cfg.fail_fast == config_consumer.DEFAULT_FAIL_FAST


def test_unknown_keys_ignored(tmp_path):
    cfg = load_orchestration_config(
        write_config(tmp_path, "retry_limit: 2\nsecret_key: nope\nextra: 1\n"))
    assert cfg.retry_limit == 2
    assert not hasattr(cfg, "secret_key")


# --------------------------------------------------------------- env var path

def test_env_var_path_used_when_no_arg(tmp_path, monkeypatch):
    path = write_config(tmp_path, "queue_name: from-env\n")
    monkeypatch.setenv(config_consumer.ENV_CONFIG_PATH, str(path))
    assert load_orchestration_config().queue_name == "from-env"


def test_explicit_path_beats_env_var(tmp_path, monkeypatch):
    env_path = write_config(tmp_path, "queue_name: from-env\n")
    monkeypatch.setenv(config_consumer.ENV_CONFIG_PATH, str(env_path))
    arg_path = tmp_path / "explicit.yaml"
    arg_path.write_text("queue_name: from-arg\n", encoding="utf-8")
    assert load_orchestration_config(arg_path).queue_name == "from-arg"


def test_env_var_pointing_at_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv(config_consumer.ENV_CONFIG_PATH, str(tmp_path / "gone.yaml"))
    assert load_orchestration_config() == OrchestrationConfig()


def test_default_filename_in_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(config_consumer.ENV_CONFIG_PATH, raising=False)
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path, "queue_name: from-cwd\n")
    assert load_orchestration_config().queue_name == "from-cwd"


# --------------------------------------------- ORCH_* consumption (not just loading)
# The suite above proves the loader PARSES correctly. It does not prove the fleet's
# ORCH_* environment settings are actually CONSUMED — every test above would still
# pass if the DEFAULT_* constants stopped reading os.environ entirely, because each
# one supplies its own YAML. These tests close that gap: they pin that an operator
# setting ORCH_MAX_PARALLEL_TASKS really does change behaviour, and that file values
# still win over it.
import importlib  # noqa: E402


def _reload_with_env(monkeypatch, **env):
    """Re-import the module so module-level ORCH_* defaults are re-read.

    The DEFAULT_* constants are captured at import time, so an env var exported
    after import is invisible. Reloading is what makes that dependency explicit
    rather than accidental — and is why config must be set before the process
    starts, not after.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(config_consumer)


def test_orch_env_vars_are_consumed_as_defaults(monkeypatch, tmp_path):
    mod = _reload_with_env(
        monkeypatch,
        ORCH_MAX_PARALLEL_TASKS="11",
        ORCH_POLL_INTERVAL_SECONDS="0.25",
        ORCH_RETRY_LIMIT="9",
        ORCH_QUEUE_NAME="from-env",
        ORCH_FAIL_FAST="true",
    )
    try:
        cfg = mod.load_orchestration_config(tmp_path / "absent.yaml")
        assert cfg.max_parallel_tasks == 11
        assert cfg.poll_interval_seconds == 0.25
        assert cfg.retry_limit == 9
        assert cfg.queue_name == "from-env"
        assert cfg.fail_fast is True
    finally:
        importlib.reload(config_consumer)


def test_file_values_win_over_orch_env_defaults(monkeypatch, tmp_path):
    mod = _reload_with_env(monkeypatch, ORCH_QUEUE_NAME="from-env", ORCH_RETRY_LIMIT="9")
    try:
        path = write_config(tmp_path, "queue_name: from-file\n")
        cfg = mod.load_orchestration_config(path)
        assert cfg.queue_name == "from-file"   # file beats env
        assert cfg.retry_limit == 9            # env still fills the key the file omits
    finally:
        importlib.reload(config_consumer)


def test_garbage_orch_env_does_not_crash_the_loader(monkeypatch, tmp_path):
    """A typo in an exported ORCH_* value must not take the fleet down."""
    mod = _reload_with_env(monkeypatch, ORCH_MAX_PARALLEL_TASKS="not-a-number")
    try:
        cfg = mod.load_orchestration_config(tmp_path / "absent.yaml")
        assert isinstance(cfg.max_parallel_tasks, int)
    finally:
        importlib.reload(config_consumer)


def test_explicit_path_beats_env_config_path(monkeypatch, tmp_path):
    """Documented precedence: explicit argument > ORCH_CONFIG_PATH > orchestration.yaml."""
    explicit = write_config(tmp_path, "queue_name: explicit\n")
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    env_path = env_dir / "orchestration.yaml"
    env_path.write_text("queue_name: env\n", encoding="utf-8")
    monkeypatch.setenv(config_consumer.ENV_CONFIG_PATH, str(env_path))
    assert load_orchestration_config(explicit).queue_name == "explicit"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
