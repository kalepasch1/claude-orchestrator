import threading
import asyncio
import time

import pytest

import swarm_executor
import parallel_dispatch
import provider_failover_sla
import symbol_context


class AliveThread:
    def is_alive(self):
        return True


def test_alive_but_unready_runtime_does_not_return_early(monkeypatch):
    runtime = swarm_executor._PersistentRuntime()
    runtime.thread = AliveThread()
    monkeypatch.setenv("ORCH_SWARM_START_TIMEOUT", "0.01")
    with pytest.raises(RuntimeError, match="failed to start"):
        runtime.start()


def test_ready_runtime_returns_without_restarting(monkeypatch):
    runtime = swarm_executor._PersistentRuntime()
    runtime.thread = AliveThread()
    runtime.ready.set()
    monkeypatch.setenv("ORCH_SWARM_START_TIMEOUT", "0.01")
    runtime.start()


def test_runtime_surfaces_initialization_error(monkeypatch):
    runtime = swarm_executor._PersistentRuntime()
    runtime.thread = AliveThread()
    runtime.startup_error = ValueError("bad session")
    runtime.ready.set()
    monkeypatch.setenv("ORCH_SWARM_START_TIMEOUT", "0.01")
    with pytest.raises(RuntimeError, match="bad session"):
        runtime.start()


def test_repo_context_scans_do_not_serialize_async_batch(monkeypatch, tmp_path):
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}
    def slow_scan(*args, **kwargs):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        time.sleep(0.1)
        with lock:
            active["n"] -= 1
        return {}

    async def fake_diff(*args, **kwargs):
        return {"text": "ok", "cost_usd": 0, "input_tokens": 1,
                "output_tokens": 1, "returncode": 0, "coder": "test"}

    monkeypatch.setattr(swarm_executor, "_read_repo_files", slow_scan)
    monkeypatch.setattr(swarm_executor, "_execute_diff", fake_diff)
    monkeypatch.setattr(swarm_executor, "_record_spend", lambda *a: None)

    async def run_batch():
        return await asyncio.gather(*(swarm_executor.execute_one(
            "task", "model", "test", str(tmp_path), mode="diff",
            apply_diff=False, repo_cache=True, session=object()) for _ in range(3)))

    results = asyncio.run(run_batch())
    assert active["peak"] >= 2
    assert all(r["returncode"] == 0 for r in results)


def test_api_task_preparation_is_concurrent(monkeypatch):
    tasks = [{"id": str(i), "slug": f"t-{i}"} for i in range(3)]
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}
    def slow_prepare(task):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        time.sleep(0.1)
        with lock:
            active["n"] -= 1
        return {"task": task, "prepare_error": "stop-after-prepare"}
    monkeypatch.setattr(parallel_dispatch, "_prepare_api_task", slow_prepare)
    parallel_dispatch._prepare_api_tasks(tasks)
    assert active["peak"] >= 2


def test_provider_state_cache_avoids_repeated_control_plane_reads(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setenv("ORCH_PROVIDER_SLA_CACHE_SEC", "30")
    provider_failover_sla._LOAD_CACHE.update({"at": 0.0, "path": "", "state": None})
    calls = []
    monkeypatch.setattr(provider_failover_sla.db, "select", lambda *a, **k: calls.append(1) or [])
    provider_failover_sla._load(); provider_failover_sla._load()
    assert len(calls) == 1


def test_symbol_context_selection_does_not_block_event_loop(monkeypatch):
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}
    def slow_select(*args, **kwargs):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        time.sleep(0.1)
        with lock: active["n"] -= 1
        return {"chunks": {}, "root": "r", "chars": 0}
    async def fake_dispatch(*args, **kwargs):
        return {"text": "ok", "cost_usd": 0, "input_tokens": 1,
                "output_tokens": 1, "returncode": 0, "coder": "test"}
    monkeypatch.setattr(symbol_context, "select", slow_select)
    monkeypatch.setattr(swarm_executor, "_dispatch", fake_dispatch)

    async def run_batch():
        return await asyncio.gather(*(swarm_executor._execute_diff(
            object(), "test", "model", "task", {}, repo="/repo") for _ in range(3)))
    asyncio.run(run_batch())
    assert active["peak"] >= 2


def test_release_repairs_are_isolated_from_slow_regular_batch():
    tasks = [{"slug": "feature-a"}, {"slug": "qafix-app-a1b2c3d4e5f6"},
             {"slug": "canary-b"}, {"slug": "relfix-app-1234"}]
    groups = parallel_dispatch._api_dispatch_groups(tasks)
    assert [t["slug"] for t in groups[0]] == ["qafix-app-a1b2c3d4e5f6", "relfix-app-1234"]
    assert [t["slug"] for t in groups[1]] == ["feature-a", "canary-b"]


def test_failed_forced_provider_patch_falls_back_to_cli(monkeypatch):
    monkeypatch.setenv("ORCH_NATIVE_MODE", "on")
    task = {
        "slug": "qafix-app-a1b2c3d4e5f6",
        "prompt": "repair the release gate",
        "force_coder": "swarm:xai",
        "note": "patch-fabric-fail:extract: model returned no unified diff",
    }
    assert parallel_dispatch._is_api_eligible(task) is False
