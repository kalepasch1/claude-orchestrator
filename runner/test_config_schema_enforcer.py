#!/usr/bin/env python3
"""Tests for config_schema_enforcer.py - schema enforcement for fleet config."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import config_schema_enforcer as cse


# --- Basic validation ---

def test_valid_int():
    r = cse.validate_config({"MAX_PARALLEL": "4"})
    assert r["valid"]
    assert r["parsed"]["MAX_PARALLEL"] == 4


def test_valid_float():
    r = cse.validate_config({"PER_TASK_GB": "2.5"})
    assert r["valid"]
    assert r["parsed"]["PER_TASK_GB"] == 2.5


def test_valid_bool_true():
    r = cse.validate_config({"ORCH_AUTO_PULL": "true"})
    assert r["valid"]
    assert r["parsed"]["ORCH_AUTO_PULL"] is True


def test_valid_bool_false():
    r = cse.validate_config({"ORCH_AUTO_PULL": "off"})
    assert r["valid"]
    assert r["parsed"]["ORCH_AUTO_PULL"] is False


def test_int_out_of_range():
    r = cse.validate_config({"MAX_PARALLEL": "100"})
    assert not r["valid"]
    assert any("out of range" in e["error"] for e in r["errors"])


def test_float_out_of_range():
    r = cse.validate_config({"PER_TASK_GB": "0.1"})
    assert not r["valid"]


def test_invalid_bool():
    r = cse.validate_config({"ORCH_AUTO_PULL": "maybe"})
    assert not r["valid"]
    assert any("boolean" in e["error"] for e in r["errors"])


def test_int_parse_error():
    r = cse.validate_config({"MAX_PARALLEL": "abc"})
    assert not r["valid"]


# --- Unknown keys ---

def test_unknown_key_non_strict():
    cse.STRICT = False
    r = cse.validate_config({"MY_CUSTOM_KEY": "hello"})
    assert r["valid"]
    assert len(r["warnings"]) == 1
    assert "unknown" in r["warnings"][0]["warning"]


def test_unknown_key_strict():
    cse.STRICT = True
    r = cse.validate_config({"MY_CUSTOM_KEY": "hello"})
    assert not r["valid"]
    assert any("unknown" in e["error"] for e in r["errors"])
    cse.STRICT = False


# --- Cross-key constraints ---

def test_cross_key_ram_floor_too_low():
    r = cse.validate_config({"RAM_FLOOR_GB": "1.0", "PER_TASK_GB": "4.0"})
    assert not r["valid"]
    assert any("RAM_FLOOR_GB" in e["error"] for e in r["errors"])


def test_cross_key_ram_floor_ok():
    r = cse.validate_config({"RAM_FLOOR_GB": "8.0", "PER_TASK_GB": "2.0"})
    assert r["valid"]


def test_cross_key_too_many_slots():
    r = cse.validate_config({"MAX_PARALLEL": "20", "ORCH_EXTRA_CODERS": "10"})
    assert not r["valid"]
    assert any("25" in e["error"] for e in r["errors"])


def test_cross_key_slots_ok():
    r = cse.validate_config({"MAX_PARALLEL": "4", "ORCH_EXTRA_CODERS": "2"})
    assert r["valid"]


# --- Mixed valid/invalid ---

def test_mixed_config():
    r = cse.validate_config({
        "MAX_PARALLEL": "4",        # valid
        "PER_TASK_GB": "999",       # out of range
        "ORCH_AUTO_PULL": "true",   # valid
    })
    assert not r["valid"]
    assert len(r["errors"]) >= 1
    assert "MAX_PARALLEL" in r["parsed"]
    assert "PER_TASK_GB" not in r["parsed"]


# --- Diff validation ---

def test_validate_diff_detects_changes():
    old = {"MAX_PARALLEL": "4", "ORCH_AUTO_PULL": "true"}
    new = {"MAX_PARALLEL": "8", "ORCH_AUTO_PULL": "true"}
    r = cse.validate_diff(old, new)
    assert r["valid"]
    assert len(r["changes"]) == 1
    assert r["changes"][0]["key"] == "MAX_PARALLEL"
    assert r["changes"][0]["old"] == "4"
    assert r["changes"][0]["new"] == "8"


def test_validate_diff_no_changes():
    cfg = {"MAX_PARALLEL": "4"}
    r = cse.validate_diff(cfg, cfg)
    assert r["valid"]
    assert len(r["changes"]) == 0


def test_validate_diff_invalid_change():
    old = {"MAX_PARALLEL": "4"}
    new = {"MAX_PARALLEL": "100"}
    r = cse.validate_diff(old, new)
    assert not r["valid"]


# --- Defaults ---

def test_defaults_returns_all():
    d = cse.defaults()
    assert "MAX_PARALLEL" in d
    assert d["MAX_PARALLEL"] == 4
    assert "PER_TASK_GB" in d
    assert isinstance(d["ORCH_AUTO_PULL"], bool)


# --- Schema info ---

def test_schema_info_single():
    info = cse.schema_info("MAX_PARALLEL")
    assert info is not None
    assert info["type"] == "int"
    assert "description" in info


def test_schema_info_all():
    info = cse.schema_info()
    assert len(info) >= 10
    assert "MAX_PARALLEL" in info


def test_schema_info_unknown():
    assert cse.schema_info("NONEXISTENT") is None


# --- Empty/None inputs ---

def test_validate_empty():
    r = cse.validate_config({})
    assert r["valid"]


def test_validate_none():
    r = cse.validate_config(None)
    assert r["valid"]


def test_diff_none():
    r = cse.validate_diff(None, None)
    assert r["valid"]


# --- Disabled mode ---

def test_disabled_passes_everything():
    cse.ENABLED = False
    r = cse.validate_config({"MAX_PARALLEL": "999"})
    assert r["valid"]
    cse.ENABLED = True


if __name__ == "__main__":
    test_valid_int()
    test_valid_float()
    test_valid_bool_true()
    test_valid_bool_false()
    test_int_out_of_range()
    test_float_out_of_range()
    test_invalid_bool()
    test_int_parse_error()
    test_unknown_key_non_strict()
    test_unknown_key_strict()
    test_cross_key_ram_floor_too_low()
    test_cross_key_ram_floor_ok()
    test_cross_key_too_many_slots()
    test_cross_key_slots_ok()
    test_mixed_config()
    test_validate_diff_detects_changes()
    test_validate_diff_no_changes()
    test_validate_diff_invalid_change()
    test_defaults_returns_all()
    test_schema_info_single()
    test_schema_info_all()
    test_schema_info_unknown()
    test_validate_empty()
    test_validate_none()
    test_diff_none()
    test_disabled_passes_everything()
    print("All config_schema_enforcer tests passed")
