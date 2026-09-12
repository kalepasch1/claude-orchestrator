"""Offline local-inference contract: no daemon, credentials, prompts or live state."""
import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_model_slots as slots

# Import the actual gateway without reading its .env or activating credentials.
_open = builtins.open
def _without_env(path, *args, **kwargs):
    if os.fspath(path).endswith("/.env"):
        raise FileNotFoundError("offline test")
    return _open(path, *args, **kwargs)
with patch("builtins.open", side_effect=_without_env), patch.dict(sys.modules, {
    "provider_credentials": types.SimpleNamespace(activate_aliases=lambda: None),
}):
    import model_gateway as gateway

GIB = 1024 ** 3


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def stub(self, target, name, **kwargs):
        stub = patch.object(target, name, **kwargs)
        value = stub.start()
        self.addCleanup(stub.stop)
        return value


class HostAdmissionTests(IsolatedTest):
    def host(self, free=20, pressure=1, load=.25):
        return slots.host_admission_status(free_fn=lambda: free,
                                          pressure_fn=lambda: pressure, load_fn=lambda: load)

    def test_healthy_host_without_model_metadata(self):
        with patch.object(slots, "_read_models", side_effect=AssertionError("no model reads")):
            status = self.host()
        self.assertTrue(status["admitted"])
        self.assertEqual(status["unit"], "GiB")
        self.assertEqual(status["headroom_gb"], 8)

    def test_warning_pressure_defers(self):
        self.assertEqual(self.host(pressure=2)["reason"], "memory_pressure")

    def test_critical_pressure_defers(self):
        self.assertEqual(self.host(pressure=4)["reason"], "memory_pressure")

    def test_unknown_pressure_defers(self):
        for pressure in (None, 0, "1", 9, True):
            with self.subTest(pressure=pressure):
                self.assertEqual(self.host(pressure=pressure)["reason"], "telemetry_unknown")

    def test_unknown_or_invalid_free_memory_defers(self):
        for free in (None, float("nan"), float("inf"), -1, "bad", True):
            with self.subTest(free=free):
                self.assertEqual(self.host(free=free)["reason"], "telemetry_unknown")

    def test_low_or_zero_free_memory_defers(self):
        for free in (0, 7.99):
            self.assertEqual(self.host(free=free)["reason"], "host_headroom")

    def test_unknown_load_defers(self):
        for load in (None, -1, float("inf"), float("nan"), True):
            self.assertEqual(self.host(load=load)["reason"], "telemetry_unknown")

    def test_high_load_defers(self):
        self.assertEqual(self.host(load=1.51)["reason"], "host_load")

    def test_load_ceiling_configurable_but_bounded(self):
        os.environ["ORCH_OLLAMA_MAX_LOAD_PER_CORE"] = "2"
        self.assertTrue(self.host(load=1.6)["admitted"])
        os.environ["ORCH_OLLAMA_MAX_LOAD_PER_CORE"] = "9999"
        self.assertEqual(self.host(load=4.1)["reason"], "host_load")

    def test_legacy_switches_cannot_disable_memory_requirement(self):
        os.environ.update(ORCH_OLLAMA_ADMIT_WAIT_S="0", ORCH_OLLAMA_SLOT_SCHEDULER="false",
                          ORCH_OLLAMA_ADMIT_HEADROOM_GB="0")
        self.assertEqual(self.host(free=7)["reason"], "host_headroom")

    def test_telemetry_exception_is_unknown(self):
        self.assertEqual(slots.host_admission_status(free_fn=lambda: 1 / 0)["reason"], "telemetry_unknown")


class NativeTelemetryTests(IsolatedTest):
    def test_darwin_bytes_are_gib_not_decimal_gb(self):
        vm = "page size of 16384 bytes\nAnonymous pages: 65536.\nPages wired down: 65536.\nPages occupied by compressor: 65536.\n"
        with patch.object(slots.sys, "platform", "darwin"), patch.object(slots.subprocess, "check_output", side_effect=[str(16 * GIB), vm]) as read:
            self.assertEqual(slots._free_ram_gb(), 13)
        self.assertTrue(all(call.kwargs["timeout"] == 2 for call in read.call_args_list))

    def test_darwin_missing_field_never_assumed_zero(self):
        with patch.object(slots.sys, "platform", "darwin"), patch.object(slots.subprocess, "check_output", side_effect=[str(16 * GIB), "page size of 16384 bytes\n"]):
            self.assertIsNone(slots._free_ram_gb())

    def test_darwin_unknown_page_size_defers(self):
        with patch.object(slots.sys, "platform", "darwin"), patch.object(slots.subprocess, "check_output", side_effect=[str(16 * GIB), "invalid"]):
            self.assertIsNone(slots._free_ram_gb())

    def test_native_timeout_is_unknown(self):
        with patch.object(slots.sys, "platform", "darwin"), patch.object(slots.subprocess, "check_output", side_effect=subprocess.TimeoutExpired("vm_stat", 2)):
            self.assertIsNone(slots._free_ram_gb())
            self.assertIsNone(slots._pressure_level())

    def test_linux_available_memory_uses_kib_to_gib(self):
        with patch.object(slots.sys, "platform", "linux"), patch.object(slots, "_read_proc", return_value="MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n"):
            self.assertEqual(slots._free_ram_gb(), 8)

    def test_linux_missing_available_does_not_guess_from_free(self):
        with patch.object(slots.sys, "platform", "linux"), patch.object(slots, "_read_proc", return_value="MemTotal: 16777216 kB\nMemFree: 8388608 kB\n"):
            self.assertIsNone(slots._free_ram_gb())

    def test_linux_inconsistent_telemetry_defers(self):
        with patch.object(slots.sys, "platform", "linux"), patch.object(slots, "_read_proc", return_value="MemTotal: 1 kB\nMemAvailable: 2 kB\n"):
            self.assertIsNone(slots._free_ram_gb())

    def test_linux_pressure_normal_warning_critical(self):
        for some, full, expected in [(0.2, 0, 1), (1, 0, 2), (0, .1, 2), (10, 0, 4), (0, 1, 4)]:
            raw = f"some avg10={some} avg60=0.00 avg300=0.00 total=100\nfull avg10={full} avg60=0.00 avg300=0.00 total=10\n"
            with self.subTest(some=some, full=full), patch.object(slots.sys, "platform", "linux"), patch.object(slots, "_read_proc", return_value=raw):
                self.assertEqual(slots._pressure_level(), expected)

    def test_linux_unknown_pressure_defers(self):
        for raw in ("", "some avg10=0\n", "some avg10=nan\nfull avg10=0\n", "some avg10=-1\nfull avg10=0\n"):
            with patch.object(slots.sys, "platform", "linux"), patch.object(slots, "_read_proc", return_value=raw):
                self.assertIsNone(slots._pressure_level())

    def test_unsupported_platform_is_explicitly_unavailable(self):
        with patch.object(slots.sys, "platform", "win32"):
            self.assertIsNone(slots._pressure_level())
            self.assertIsNone(slots._free_ram_gb())


class ModelAdmissionTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.stub(slots, "_read_models", return_value=[])
        self.unload = self.stub(slots, "unload", side_effect=AssertionError("must never evict"))

    def admit(self, model="llama3.2:3b", free=20, resident=None):
        return slots.admission_status(model, free_fn=lambda: free, pressure_fn=lambda: 1,
                                      load_fn=lambda: .25, resident_fn=lambda: [] if resident is None else resident)

    def test_small_model_admitted_with_headroom(self):
        self.assertTrue(self.admit()["admitted"])

    def test_small_model_denied_without_additional_allocation_headroom(self):
        self.assertEqual(self.admit(free=9)["reason"], "host_headroom")

    def test_unknown_model_denied(self):
        self.assertEqual(self.admit(model="private-alias")["reason"], "model_memory_unknown")

    def test_missing_model_denied(self):
        self.assertEqual(self.admit(model=None)["reason"], "model_unknown")

    def test_large_name_estimate_denied_even_with_free_ram(self):
        self.assertEqual(self.admit(model="qwen3.5:27b-mlx", free=40)["reason"], "model_allocation_limit")

    def test_disk_metadata_plus_context_is_conservative(self):
        with patch.object(slots, "_read_models", return_value=[{"name": "llama3.2:3b", "size": 3 * GIB}]):
            result = self.admit()
        self.assertEqual(result["allocation_gb"], 5.6)

    def test_actual_resident_oversize_overrides_small_label(self):
        resident = [{"name": "llama3.2:3b", "size_vram": 21 * GIB, "context_length": 4096}]
        result = self.admit(free=40, resident=resident)
        self.assertEqual(result["reason"], "model_allocation_limit")
        self.assertEqual(result["allocation_gb"], 21)

    def test_resident_reuse_counts_memory_once(self):
        resident = [{"name": "llama3.2:3b", "size": 6 * GIB, "size_vram": 5 * GIB, "context_length": 4096}]
        result = self.admit(free=9, resident=resident)
        self.assertTrue(result["admitted"])
        self.assertEqual(result["allocation_gb"], 6)
        self.assertEqual(result["additional_gb"], 0)
        self.unload.assert_not_called()

    def test_other_possibly_active_resident_is_not_evicted(self):
        result = self.admit(resident=[{"name": "another:3b", "size_vram": 3 * GIB}])
        self.assertEqual(result["reason"], "other_model_resident")
        self.unload.assert_not_called()

    def test_healthy_completion_hook_does_not_unload(self):
        self.assertFalse(slots.maybe_unload_after("qwen3.5:27b-mlx"))
        self.unload.assert_not_called()

    def test_context_growth_reserves_additional_memory(self):
        result = self.admit(free=9, resident=[{"name": "llama3.2:3b", "size_vram": 2 * GIB, "context_length": 512}])
        self.assertEqual(result["reason"], "host_headroom")
        self.assertGreater(result["additional_gb"], 0)

    def test_unknown_resident_metadata_denied(self):
        for resident in ([{}], ["bad"], [{"name": "llama3.2:3b"}], [{"name": "llama3.2:3b", "size": -1}]):
            self.assertFalse(self.admit(resident=resident)["admitted"])

    def test_metadata_outage_does_not_mean_no_models_loaded(self):
        with patch.object(slots, "_resident_models", return_value=None):
            status = slots.admission_status("llama3.2:3b", free_fn=lambda: 20,
                                            pressure_fn=lambda: 1, load_fn=lambda: .2)
        self.assertEqual(status["reason"], "telemetry_unknown")


class RequestPolicyTests(IsolatedTest):
    def test_finite_safe_defaults(self):
        self.assertEqual(slots.request_policy(), {"num_ctx": 4096, "num_predict": 1024,
                                                  "keep_alive": "60s", "timeout_s": 90})

    def test_context_and_output_cannot_be_disabled_or_infinite(self):
        for value in ("0", "-1", "16384", "inf", "nan", "bad"):
            os.environ.update(ORCH_OLLAMA_NUM_CTX=value, ORCH_OLLAMA_NUM_PREDICT=value)
            result = slots.request_policy()
            self.assertGreaterEqual(result["num_ctx"], 256)
            self.assertLessEqual(result["num_ctx"], 4096)
            self.assertGreaterEqual(result["num_predict"], 1)
            self.assertLessEqual(result["num_predict"], 1024)

    def test_keep_alive_never_indefinite_or_long(self):
        for raw, expected in [("-1", "60s"), ("1h", "120s"), ("inf", "60s"), ("nan", "60s"), ("30s", "30s")]:
            os.environ["ORCH_OLLAMA_KEEP_ALIVE"] = raw
            self.assertEqual(slots.request_policy()["keep_alive"], expected)

    def test_request_timeout_is_bounded(self):
        os.environ["ORCH_OLLAMA_REQUEST_TIMEOUT_S"] = "600"
        self.assertEqual(slots.request_policy()["timeout_s"], 180)


class GatewaySafetyTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.post = self.stub(gateway, "_post", return_value={"response": "complete", "done": True, "done_reason": "stop"})
        self.slot = self.stub(slots, "slot", side_effect=lambda *a, **k: contextlib.nullcontext({"admitted": True, "locked": True}))
        self.stub(gateway, "_sensitivity", return_value="standard")
        self.stub(gateway, "_provider_allowed", return_value=True)
        self.learned = self.stub(gateway, "_learned_route", return_value=("openai", "gpt-test", "test"))
        self.fallback = self.stub(gateway, "_fallbacks", return_value=iter([]))
        self.record = self.stub(gateway, "_record_operation")
        modules = patch.dict(sys.modules, {
            "prompt_result_cache": types.SimpleNamespace(lookup=lambda *a: None, store=lambda *a: None),
            "provider_failover_sla": types.SimpleNamespace(record_probe_success=lambda *a: None),
            "usage_meter": types.SimpleNamespace(record=lambda *a, **k: None),
        })
        modules.start()
        self.addCleanup(modules.stop)

    def complete(self, prompt="short test input", model="llama3.2:3b"):
        return gateway.complete("local", model, prompt)

    def test_success_exact_model_bounded_payload_and_timeout(self):
        text, cost = gateway._local("llama3.2:3b", "test input", timeout=600)
        self.assertEqual((text, cost), ("complete", 0))
        args, kwargs = self.post.call_args
        self.assertEqual(args[2]["model"], "llama3.2:3b")
        self.assertEqual(args[2]["options"], {"num_ctx": 4096, "num_predict": 1024})
        self.assertEqual(args[2]["keep_alive"], "60s")
        self.assertEqual(kwargs["timeout"], 90)
        self.post.assert_called_once()

    def test_explicit_local_cannot_use_learned_or_vendor_name_reroute(self):
        result = self.complete(model="local-deepseek:3b")
        self.assertEqual(result["provider"], "local")
        self.learned.assert_not_called()
        self.fallback.assert_not_called()

    def test_capacity_denial_never_posts_or_retries_or_records_prompt(self):
        self.slot.side_effect = slots.LocalCapacityError("host_headroom")
        result = self.complete(prompt="confidential sentinel input")
        self.assertTrue(result["deferred"])
        self.assertEqual(result["reason"], "host_headroom")
        self.assertNotIn("sentinel", json.dumps(result))
        self.post.assert_not_called()
        self.fallback.assert_not_called()
        self.record.assert_not_called()

    def test_missing_guard_never_posts(self):
        with patch.dict(sys.modules, {"local_model_slots": None}):
            result = self.complete()
        self.assertEqual(result["reason"], "guard_unavailable")
        self.post.assert_not_called()

    def test_old_fail_open_guard_metadata_rejected(self):
        for metadata in (None, {}, {"locked": False}, {"admitted": True, "locked": False}):
            self.slot.side_effect = lambda *a, **k: contextlib.nullcontext(metadata)
            self.assertEqual(self.complete()["reason"], "guard_unavailable")
        self.post.assert_not_called()

    def test_missing_model_does_not_select_catalog_replacement(self):
        self.assertEqual(self.complete(model=None)["reason"], "model_unknown")
        self.post.assert_not_called()

    def test_local_disable_is_enforced_at_request_boundary(self):
        os.environ["ORCH_DISABLE_LOCAL_MODELS"] = "1"
        self.assertEqual(self.complete()["reason"], "local_disabled")
        self.post.assert_not_called()

    def test_large_input_is_not_truncated_or_rerouted(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = self.complete(prompt="private-sentinel-" * 2000)
        self.assertEqual(result["reason"], "context_budget")
        self.assertNotIn("private", output.getvalue() + json.dumps(result))
        self.post.assert_not_called()
        self.slot.assert_not_called()
        self.record.assert_not_called()
        self.fallback.assert_not_called()

    def test_multibyte_input_uses_utf8_budget(self):
        self.assertEqual(self.complete(prompt="界" * 1000)["reason"], "context_budget")
        self.post.assert_not_called()

    def test_exact_input_budget_accepted(self):
        self.assertEqual(self.complete(prompt="x" * (4096 - 1024 - 256))["text"], "complete")

    def test_length_limited_output_never_reported_complete(self):
        self.post.return_value = {"response": "partial conclusion", "done": True, "done_reason": "length"}
        result = self.complete()
        self.assertEqual(result["reason"], "generation_limit")
        self.assertEqual(result["text"], "")
        self.record.assert_not_called()

    def test_missing_or_false_done_is_incomplete(self):
        for response in ({"response": "partial"}, {"done": False, "response": "partial"}, None):
            self.post.return_value = response
            self.assertEqual(self.complete()["reason"], "response_incomplete")

    def test_empty_or_nontext_response_is_not_success(self):
        for response in ("", "  ", None, ["invalid"]):
            self.post.return_value = {"done": True, "response": response}
            self.assertEqual(self.complete()["reason"], "response_incomplete")

    def test_server_busy_503_defers_once(self):
        self.post.side_effect = urllib.error.HTTPError("http://test", 503, "private error body", {}, None)
        result = self.complete()
        self.assertEqual(result["reason"], "server_busy")
        self.post.assert_called_once()
        self.fallback.assert_not_called()
        self.record.assert_not_called()
        self.assertNotIn("private", json.dumps(result))

    def test_timeout_defers_once(self):
        self.post.side_effect = TimeoutError("private request contents")
        self.assertEqual(self.complete()["reason"], "request_timeout")
        self.post.assert_called_once()
        self.record.assert_not_called()

    def test_wrapped_timeout_defers(self):
        self.post.side_effect = urllib.error.URLError(TimeoutError("private request"))
        self.assertEqual(self.complete()["reason"], "request_timeout")

    def test_invalid_model_http_error_is_not_success_or_capacity(self):
        self.post.side_effect = urllib.error.HTTPError("http://test", 400, "invalid model", {}, None)
        result = self.complete()
        self.assertIn("error", result)
        self.assertFalse(result.get("deferred", False))
        self.assertEqual(result["text"], "")
        self.post.assert_called_once()
        self.fallback.assert_not_called()

    def test_cloud_fallback_local_denial_stops_further_substitution(self):
        self.learned.return_value = None
        self.fallback.return_value = iter([("local", "llama3.2:3b"), ("google", "gemini-test")])
        with patch.object(gateway, "_call_provider", side_effect=[RuntimeError("cloud unavailable"), slots.LocalCapacityError("host_headroom")]) as call:
            result = gateway.complete("openai", "gpt-test", "test input")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result["reason"], "host_headroom")

    def test_legacy_completion_has_structured_denial(self):
        self.slot.side_effect = slots.LocalCapacityError("slot_busy")
        result = gateway.complete_legacy("local", "llama3.2:3b", "test")
        self.assertTrue(result["deferred"])
        self.assertEqual(result["reason"], "slot_busy")


class ReceiptTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="consilium-admission-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "orch-local-capacity-test.json"
        self.path.write_text('{"deferred":false}')
        os.environ["ORCH_LOCAL_CAPACITY_RECEIPT"] = str(self.path)

    def test_atomic_reason_only_receipt(self):
        error = slots.LocalCapacityError("host_headroom")
        self.assertEqual(json.loads(self.path.read_text()), {"deferred": True, "reason": "host_headroom"})
        self.assertEqual(error.reason, "host_headroom")
        self.assertLess(self.path.stat().st_size, 100)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.directory.glob(".capacity-*")), [])

    def test_unsafe_reason_cannot_record_prompt_text(self):
        error = slots.LocalCapacityError("private prompt contents")
        self.assertEqual(error.reason, "capacity_unavailable")
        self.assertNotIn("private", self.path.read_text())

    def test_receipt_write_failure_never_admits(self):
        with patch.object(slots.os, "replace", side_effect=PermissionError("private path")):
            error = slots.LocalCapacityError("slot_busy")
        self.assertEqual(error.reason, "slot_busy")
        self.assertEqual(list(self.directory.glob(".capacity-*")), [])

    def test_symlink_target_is_not_overwritten(self):
        target = self.directory / "untouched.json"
        target.write_text("untouched")
        self.path.unlink()
        self.path.symlink_to(target)
        slots.LocalCapacityError("slot_busy")
        self.assertEqual(target.read_text(), "untouched")
        self.assertTrue(self.path.is_symlink())

    def test_broad_or_unexpected_target_not_written(self):
        target = self.directory / "unrelated.json"
        target.write_text("untouched")
        os.environ["ORCH_LOCAL_CAPACITY_RECEIPT"] = str(target)
        slots.LocalCapacityError("slot_busy")
        self.assertEqual(target.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
