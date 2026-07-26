"""Comprehensive tests for SharedDiscoveryBus."""

import pytest
import threading
import time
import tempfile
import os
from discovery_bus import (
    SharedDiscoveryBus,
    extract_discoveries,
    get_default_bus,
    invalidate as bus_invalidate,
)


class TestSharedDiscoveryBus:
    """Test cases for SharedDiscoveryBus core functionality."""

    def test_publish_and_read_all(self):
        """Test basic publish and read_all round-trip."""
        bus = SharedDiscoveryBus()
        discovery = {
            "slug": "task-1",
            "kind": "shared_file_created",
            "summary": "Created utils/helper.ts",
            "tags": ["shared", "utils"],
            "content": "export function helper() {}",
        }
        bus.publish(discovery)
        results = bus.read_all()
        assert len(results) == 1
        assert results[0]["slug"] == "task-1"
        assert results[0]["summary"] == "Created utils/helper.ts"

    def test_publish_sets_defaults(self):
        """Test that publish sets default ts and confidence."""
        bus = SharedDiscoveryBus()
        discovery = {"slug": "t1", "kind": "gotcha", "summary": "A gotcha"}
        bus.publish(discovery)
        results = bus.read_all()
        assert len(results) == 1
        assert "ts" in results[0]
        assert results[0]["confidence"] == 0.8

    def test_read_all_empty(self):
        """Test read_all on empty bus."""
        bus = SharedDiscoveryBus()
        results = bus.read_all()
        assert results == []

    def test_read_by_tags_single_tag(self):
        """Test read_by_tags with single tag match."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export", "shared"],
        })
        bus.publish({
            "slug": "t2",
            "kind": "gotcha",
            "summary": "Gotcha B",
            "tags": ["gotcha", "warning"],
        })
        results = bus.read_by_tags(["export"])
        assert len(results) == 1
        assert results[0]["slug"] == "t1"

    def test_read_by_tags_multiple_tags(self):
        """Test read_by_tags with multiple tag search."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export", "shared"],
        })
        bus.publish({
            "slug": "t2",
            "kind": "gotcha",
            "summary": "Gotcha B",
            "tags": ["gotcha", "warning"],
        })
        results = bus.read_by_tags(["export", "gotcha"])
        assert len(results) == 2

    def test_read_by_tags_no_duplicates(self):
        """Test that read_by_tags deduplicates results."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export", "shared", "api"],
        })
        results = bus.read_by_tags(["export", "shared", "api"])
        assert len(results) == 1

    def test_context_injection_empty(self):
        """Test context_injection returns empty string on empty bus."""
        bus = SharedDiscoveryBus()
        context = bus.context_injection("task-1", ["shared"])
        assert context == ""

    def test_context_injection_excludes_own_discoveries(self):
        """Test that context_injection excludes discoveries from the same task."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "task-1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export"],
        })
        context = bus.context_injection("task-1", ["export"])
        assert "Export A" not in context
        assert "SIBLING TASK DISCOVERIES" not in context

    def test_context_injection_includes_tag_overlap(self):
        """Test context_injection includes discoveries with tag overlap."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "task-1",
            "kind": "export",
            "summary": "Export helper",
            "tags": ["export", "shared"],
            "content": "export const helper = () => {}",
        })
        context = bus.context_injection("task-2", ["shared", "utils"])
        assert "Export helper" in context
        assert "SIBLING TASK DISCOVERIES" in context
        assert "export const helper" in context

    def test_context_injection_includes_high_confidence(self):
        """Test context_injection includes high-confidence cross-tag discoveries."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "task-1",
            "kind": "gotcha",
            "summary": "Critical gotcha",
            "tags": ["gotcha"],
            "confidence": 0.95,
        })
        context = bus.context_injection("task-2", ["unrelated"])
        assert "Critical gotcha" in context

    def test_stats_accuracy(self):
        """Test stats returns accurate counts and categories."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export"],
        })
        bus.publish({
            "slug": "t2",
            "kind": "export",
            "summary": "Export B",
            "tags": ["export", "shared"],
        })
        bus.publish({
            "slug": "t3",
            "kind": "gotcha",
            "summary": "Gotcha C",
            "tags": ["gotcha"],
        })
        stats = bus.stats()
        assert stats["total_discoveries"] == 3
        assert stats["by_kind"]["export"] == 2
        assert stats["by_kind"]["gotcha"] == 1
        assert "export" in stats["active_tags"]
        assert "gotcha" in stats["active_tags"]
        assert len(stats["tasks_contributing"]) == 3

    def test_invalidate_clears_everything(self):
        """Test invalidate clears discoveries, tags, and subscribers."""
        bus = SharedDiscoveryBus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export"],
        })
        called = []
        bus.subscribe(lambda d: called.append(d))
        bus.invalidate()
        assert len(bus.read_all()) == 0
        assert bus.stats()["total_discoveries"] == 0
        bus.publish({"slug": "t2", "kind": "gotcha", "summary": "B", "tags": []})
        assert len(called) == 0  # subscriber was cleared

    def test_subscribe_receives_new_discoveries(self):
        """Test subscribe callback receives all new discoveries."""
        bus = SharedDiscoveryBus()
        received = []
        bus.subscribe(lambda d: received.append(d))
        bus.publish({"slug": "t1", "kind": "export", "summary": "A", "tags": []})
        bus.publish({"slug": "t2", "kind": "gotcha", "summary": "B", "tags": []})
        assert len(received) == 2
        assert received[0]["slug"] == "t1"
        assert received[1]["slug"] == "t2"

    def test_subscribe_with_filter(self):
        """Test subscribe with filter_fn only receives matching discoveries."""
        bus = SharedDiscoveryBus()
        received = []
        bus.subscribe(
            lambda d: received.append(d),
            filter_fn=lambda d: d.get("kind") == "export",
        )
        bus.publish({"slug": "t1", "kind": "export", "summary": "A", "tags": []})
        bus.publish({"slug": "t2", "kind": "gotcha", "summary": "B", "tags": []})
        bus.publish({"slug": "t3", "kind": "export", "summary": "C", "tags": []})
        assert len(received) == 2
        assert all(d["kind"] == "export" for d in received)

    def test_thread_safety_concurrent_publish(self):
        """Test thread safety with concurrent publish from 10 threads."""
        bus = SharedDiscoveryBus()
        errors = []

        def publish_from_thread(thread_id):
            try:
                for i in range(10):
                    bus.publish({
                        "slug": f"t{thread_id}-{i}",
                        "kind": "export",
                        "summary": f"Export {thread_id}-{i}",
                        "tags": [f"thread-{thread_id}"],
                    })
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publish_from_thread, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(bus.read_all()) == 100  # 10 threads * 10 publishes

    def test_thread_safety_concurrent_read_write(self):
        """Test thread safety with concurrent read and write."""
        bus = SharedDiscoveryBus()
        errors = []

        def writer(thread_id):
            try:
                for i in range(20):
                    bus.publish({
                        "slug": f"w{thread_id}-{i}",
                        "kind": "export",
                        "summary": f"W {thread_id}-{i}",
                        "tags": ["write"],
                    })
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(40):
                    bus.read_all()
                    bus.read_by_tags(["write"])
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        threads.append(threading.Thread(target=reader))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_read_all_with_since_ts(self):
        """Test read_all filtering by timestamp."""
        bus = SharedDiscoveryBus()
        t1 = time.time()
        bus.publish({
            "slug": "old",
            "kind": "export",
            "summary": "Old",
            "tags": [],
            "ts": t1 - 10,
        })
        time.sleep(0.01)
        t2 = time.time()
        bus.publish({
            "slug": "new",
            "kind": "export",
            "summary": "New",
            "tags": [],
            "ts": t2,
        })
        results = bus.read_all(since_ts=t1)
        assert len(results) == 1
        assert results[0]["slug"] == "new"


class TestExtractDiscoveries:
    """Test cases for extract_discoveries function."""

    def test_extract_no_diff(self):
        """Test extract_discoveries with empty/no diff."""
        discoveries = extract_discoveries("t1", ["test"], "")
        assert discoveries == []

    def test_extract_shared_file_created(self):
        """Test extraction of shared file creation."""
        diff = """+++ b/shared/types.ts
-   some old line
+export interface User {
+  id: string;
+}"""
        discoveries = extract_discoveries("t1", ["types"], diff)
        shared_file_disc = [d for d in discoveries if d["kind"] == "shared_file_created"]
        assert len(shared_file_disc) >= 1
        assert "shared/types.ts" in shared_file_disc[0]["summary"]

    def test_extract_export_created(self):
        """Test extraction of export statements."""
        diff = """+export interface User {
+  id: string;
+}"""
        discoveries = extract_discoveries("t1", ["types"], diff)
        export_disc = [d for d in discoveries if d["kind"] == "export_created"]
        assert len(export_disc) >= 1
        assert "User" in export_disc[0]["summary"]

    def test_extract_api_route_defined(self):
        """Test extraction of API route definitions."""
        diff = """+app.post('/api/users', (req, res) => {
+  res.json({ ok: true });
+})"""
        discoveries = extract_discoveries("t1", ["api"], diff)
        route_disc = [d for d in discoveries if d["kind"] == "api_route_defined"]
        assert len(route_disc) >= 1
        assert "POST" in route_disc[0]["summary"]

    def test_extract_gotcha(self):
        """Test extraction of gotcha/warning comments."""
        diff = """+// GOTCHA: This endpoint requires admin role or it's silently ignored
+app.delete('/api/admin/purge', ...);"""
        discoveries = extract_discoveries("t1", ["api"], diff)
        gotcha_disc = [d for d in discoveries if d["kind"] == "gotcha"]
        assert len(gotcha_disc) >= 1
        assert "admin role" in gotcha_disc[0]["summary"]

    def test_extract_multiple_patterns(self):
        """Test extraction with multiple discovery types in one diff."""
        diff = """+++ b/shared/api.ts
+// WORKAROUND: Supabase RLS can be flaky, retry 3 times
+export const getUser = async (id: string) => {
+  // implementation
+};
+
+// GOTCHA: Never use this without authentication
+"""
        discoveries = extract_discoveries("t1", ["api", "shared"], diff)
        assert len(discoveries) >= 2
        kinds = {d["kind"] for d in discoveries}
        assert "shared_file_created" in kinds
        assert "gotcha" in kinds

    def test_extract_with_file_content_reading(self):
        """Test extraction reads file content if repo_path provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a shared file
            shared_dir = os.path.join(tmpdir, "shared")
            os.makedirs(shared_dir)
            shared_file = os.path.join(shared_dir, "utils.ts")
            with open(shared_file, "w") as f:
                f.write("export const helper = () => 'test';\n")

            diff = "+++ b/shared/utils.ts\n+export const helper = () => 'test';"
            discoveries = extract_discoveries("t1", ["shared"], diff, repo_path=tmpdir)
            shared_disc = [d for d in discoveries if d["kind"] == "shared_file_created"]
            assert len(shared_disc) >= 1
            assert "export const helper" in shared_disc[0]["content"]

    def test_extract_confidence_levels(self):
        """Test that discoveries have appropriate confidence levels."""
        diff = """+++ b/shared/types.ts
+export interface User {}
+// GOTCHA: Very important
"""
        discoveries = extract_discoveries("t1", ["types"], diff)
        shared_disc = [d for d in discoveries if d["kind"] == "shared_file_created"]
        export_disc = [d for d in discoveries if d["kind"] == "export_created"]
        gotcha_disc = [d for d in discoveries if d["kind"] == "gotcha"]

        if shared_disc:
            assert shared_disc[0]["confidence"] == 0.95
        if export_disc:
            assert export_disc[0]["confidence"] == 0.85
        if gotcha_disc:
            assert gotcha_disc[0]["confidence"] == 0.95

    def test_extract_tags_include_discovery_kind(self):
        """Test that extracted discoveries include appropriate tags."""
        diff = "+++ b/shared/types.ts\n+export interface User {}"
        discoveries = extract_discoveries("t1", ["types"], diff)
        assert any(d.get("kind") == "shared_file_created" and "shared" in d["tags"] for d in discoveries)


class TestDefaultBus:
    """Test cases for module-level singleton."""

    def test_get_default_bus_singleton(self):
        """Test that get_default_bus returns same instance."""
        bus_invalidate()
        bus1 = get_default_bus()
        bus2 = get_default_bus()
        assert bus1 is bus2

    def test_default_bus_persist(self):
        """Test that default bus persists discoveries across calls."""
        bus_invalidate()
        bus = get_default_bus()
        bus.publish({
            "slug": "t1",
            "kind": "export",
            "summary": "Export A",
            "tags": ["export"],
        })
        bus2 = get_default_bus()
        assert len(bus2.read_all()) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
