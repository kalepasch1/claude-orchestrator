"""Tests for config_manager."""
import sys, os, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config_manager import ConfigManager

def test_get_default():
    c = ConfigManager({"key": "val"})
    assert c.get("key") == "val"

def test_get_missing():
    c = ConfigManager()
    assert c.get("nope") is None
    assert c.get("nope", "fallback") == "fallback"

def test_set_override():
    c = ConfigManager({"key": "old"})
    c.set("key", "new")
    assert c.get("key") == "new"

def test_env_override(monkeypatch):
    monkeypatch.setenv("ORCH_MY_KEY", "from_env")
    c = ConfigManager({"my_key": "default"})
    assert c.get("my_key") == "from_env"

def test_override_beats_env(monkeypatch):
    monkeypatch.setenv("ORCH_MY_KEY", "from_env")
    c = ConfigManager({"my_key": "default"})
    c.set("my_key", "override")
    assert c.get("my_key") == "override"

def test_load_file():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump({"loaded_key": "loaded_val"}, f)
        f.flush()
        c = ConfigManager()
        assert c.load_file(f.name) is True
        assert c.get("loaded_key") == "loaded_val"
    os.unlink(f.name)

def test_load_file_missing():
    c = ConfigManager()
    assert c.load_file("/nonexistent/config.json") is False

def test_validate_ok():
    c = ConfigManager({"a": 1, "b": 2})
    assert c.validate(["a", "b"]) == []

def test_validate_missing():
    c = ConfigManager({"a": 1})
    assert c.validate(["a", "b"]) == ["b"]

def test_to_dict():
    c = ConfigManager({"a": 1})
    c.set("b", 2)
    d = c.to_dict()
    assert d == {"a": 1, "b": 2}

def test_reset():
    c = ConfigManager({"a": 1})
    c.set("a", 99)
    c.reset()
    assert c.get("a") == 1

def test_coerce_bool(monkeypatch):
    monkeypatch.setenv("ORCH_FLAG", "true")
    c = ConfigManager({"flag": False})
    assert c.get("flag") is True

def test_coerce_int(monkeypatch):
    monkeypatch.setenv("ORCH_COUNT", "42")
    c = ConfigManager({"count": 0})
    assert c.get("count") == 42
