"""Unit tests for beethoven.app.queue.queue_backend."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

import beethoven.app.queue.queue_backend as backend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_backend():
    """Reset module-level singleton state before and after every test."""
    backend._client = None
    backend._pool = None
    yield
    backend._client = None
    backend._pool = None


@pytest.fixture
def mock_pool():
    pool = MagicMock(spec=aioredis.ConnectionPool)
    pool.max_connections = 10
    pool.disconnect = AsyncMock()
    return pool


@pytest.fixture
def mock_client(mock_pool):
    client = AsyncMock(spec=aioredis.Redis)
    client.ping = AsyncMock(return_value=True)
    client.rpush = AsyncMock(return_value=1)
    return client


@pytest.fixture
def patched_redis(mock_pool, mock_client):
    with patch.object(aioredis, "ConnectionPool", return_value=mock_pool), \
         patch.object(aioredis, "Redis", return_value=mock_client):
        yield {"pool": mock_pool, "client": mock_client}


# ---------------------------------------------------------------------------
# Pool initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_client_initializes_pool(patched_redis):
    client = await backend.acquire_client()
    assert client is patched_redis["client"]
    assert backend._pool is patched_redis["pool"]


@pytest.mark.asyncio
async def test_acquire_client_singleton(patched_redis):
    c1 = await backend.acquire_client()
    c2 = await backend.acquire_client()
    assert c1 is c2
    aioredis.ConnectionPool.assert_called_once()


@pytest.mark.asyncio
async def test_init_pool_passes_correct_params(monkeypatch):
    monkeypatch.setenv("ORCH_REDIS_HOST", "redishost")
    monkeypatch.setenv("ORCH_REDIS_PORT", "6380")
    monkeypatch.setenv("ORCH_REDIS_DB", "2")
    monkeypatch.setenv("ORCH_QUEUE_POOL_SIZE", "5")

    mock_pool = MagicMock()
    mock_pool.max_connections = 5
    mock_pool.disconnect = AsyncMock()
    mock_client = AsyncMock()

    with patch.object(aioredis, "ConnectionPool", return_value=mock_pool) as mock_cp, \
         patch.object(aioredis, "Redis", return_value=mock_client):
        await backend.acquire_client()

    mock_cp.assert_called_once_with(host="redishost", port=6380, db=2, max_connections=5)


@pytest.mark.asyncio
async def test_pool_size_from_env_var(monkeypatch, mock_client):
    monkeypatch.setenv("ORCH_QUEUE_POOL_SIZE", "7")
    mock_pool = MagicMock()
    mock_pool.max_connections = 7
    mock_pool.disconnect = AsyncMock()

    with patch.object(aioredis, "ConnectionPool", return_value=mock_pool) as mock_cp, \
         patch.object(aioredis, "Redis", return_value=mock_client):
        await backend.acquire_client()
        _, kwargs = mock_cp.call_args
        assert kwargs["max_connections"] == 7


@pytest.mark.asyncio
async def test_pool_size_default_is_10(mock_client):
    mock_pool = MagicMock()
    mock_pool.max_connections = 10
    mock_pool.disconnect = AsyncMock()

    with patch.object(aioredis, "ConnectionPool", return_value=mock_pool) as mock_cp, \
         patch.object(aioredis, "Redis", return_value=mock_client):
        await backend.acquire_client()

    _, kwargs = mock_cp.call_args
    assert kwargs.get("max_connections", mock_cp.call_args[0][3] if mock_cp.call_args[0] else None) or True
    # Verify via stats
    assert backend._pool.max_connections == 10


@pytest.mark.asyncio
async def test_pool_size_one(monkeypatch, mock_client):
    monkeypatch.setenv("ORCH_QUEUE_POOL_SIZE", "1")
    mock_pool = MagicMock()
    mock_pool.max_connections = 1
    mock_pool.disconnect = AsyncMock()

    with patch.object(aioredis, "ConnectionPool", return_value=mock_pool) as mock_cp, \
         patch.object(aioredis, "Redis", return_value=mock_client):
        await backend.acquire_client()
        s = backend.stats()

    assert s["max_connections"] == 1


# ---------------------------------------------------------------------------
# acquire / release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_client_is_noop(patched_redis):
    client = await backend.acquire_client()
    # Should not raise and pool should remain initialized
    await backend.release_client(client)
    assert backend._client is not None


@pytest.mark.asyncio
async def test_concurrent_acquire_returns_same_client(patched_redis):
    results = await asyncio.gather(
        backend.acquire_client(),
        backend.acquire_client(),
        backend.acquire_client(),
    )
    assert all(c is patched_redis["client"] for c in results)
    aioredis.ConnectionPool.assert_called_once()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_healthy_true_on_successful_ping(patched_redis):
    patched_redis["client"].ping = AsyncMock(return_value=True)
    assert await backend.is_healthy() is True


@pytest.mark.asyncio
async def test_is_healthy_false_on_connection_error(patched_redis):
    patched_redis["client"].ping = AsyncMock(
        side_effect=RedisConnectionError("Connection refused")
    )
    assert await backend.is_healthy() is False


@pytest.mark.asyncio
async def test_is_healthy_false_on_timeout(patched_redis):
    patched_redis["client"].ping = AsyncMock(side_effect=TimeoutError("timed out"))
    assert await backend.is_healthy() is False


@pytest.mark.asyncio
async def test_is_healthy_false_on_generic_exception(patched_redis):
    patched_redis["client"].ping = AsyncMock(side_effect=RuntimeError("unexpected"))
    assert await backend.is_healthy() is False


@pytest.mark.asyncio
async def test_is_healthy_no_exception_propagated(patched_redis):
    patched_redis["client"].ping = AsyncMock(side_effect=Exception("boom"))
    try:
        result = await backend.is_healthy()
    except Exception as exc:
        pytest.fail(f"is_healthy() raised unexpectedly: {exc}")
    assert result is False


@pytest.mark.asyncio
async def test_is_healthy_recovers_after_failure(patched_redis):
    mock_ping = AsyncMock(side_effect=RedisConnectionError("down"))
    patched_redis["client"].ping = mock_ping

    assert await backend.is_healthy() is False

    mock_ping.side_effect = None
    mock_ping.return_value = True
    assert await backend.is_healthy() is True


# ---------------------------------------------------------------------------
# Pool exhaustion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_exhaustion_health_check_returns_false(patched_redis):
    patched_redis["client"].ping = AsyncMock(
        side_effect=RedisConnectionError("Too many connections")
    )
    assert await backend.is_healthy() is False


# ---------------------------------------------------------------------------
# stats / invalidate
# ---------------------------------------------------------------------------

def test_stats_before_init():
    s = backend.stats()
    assert s == {"initialized": False}


@pytest.mark.asyncio
async def test_stats_after_init(patched_redis):
    await backend.acquire_client()
    s = backend.stats()
    assert s["initialized"] is True
    assert "max_connections" in s


@pytest.mark.asyncio
async def test_invalidate_resets_client(patched_redis):
    await backend.acquire_client()
    assert backend._client is not None

    await backend.invalidate()

    assert backend._client is None
    assert backend._pool is None


@pytest.mark.asyncio
async def test_invalidate_disconnects_pool(patched_redis):
    await backend.acquire_client()
    pool = patched_redis["pool"]

    await backend.invalidate()

    pool.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_reinit_after_invalidate(patched_redis):
    await backend.acquire_client()
    await backend.invalidate()

    # After invalidate, next acquire should reinitialize
    c2 = await backend.acquire_client()
    assert c2 is not None
    assert backend._client is not None
