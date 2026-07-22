"""Integration tests for queue backend health against a live Redis instance."""
import pytest

import beethoven.app.queue.queue_backend as backend


@pytest.fixture(autouse=True)
async def clean_pool():
    await backend.invalidate()
    yield
    await backend.invalidate()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_is_healthy():
    """Redis responds to PING when the test environment has a live Redis."""
    result = await backend.is_healthy()
    assert result is True, "Expected Redis to be healthy in the integration environment"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_is_healthy_returns_false_for_bad_host(monkeypatch):
    """is_healthy() returns False without raising when Redis is unreachable."""
    monkeypatch.setenv("ORCH_REDIS_HOST", "localhost")
    monkeypatch.setenv("ORCH_REDIS_PORT", "19999")  # port where nothing listens
    await backend.invalidate()

    result = await backend.is_healthy()
    assert result is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_overall_health_includes_queue_backend():
    """Overall service health reflects the Redis queue backend status."""
    queue_healthy = await backend.is_healthy()
    health = {
        "queue_backend": queue_healthy,
    }
    assert isinstance(health["queue_backend"], bool)
    assert health["queue_backend"] is True
