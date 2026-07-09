"""Redis connection pool singleton for the async queue backend."""
import logging
import threading

import redis.asyncio as aioredis

from beethoven.app.config.settings import get_queue_settings

_log = logging.getLogger(__name__)

_client: "aioredis.Redis | None" = None
_pool: "aioredis.ConnectionPool | None" = None
_lock = threading.Lock()


def _init_pool() -> None:
    global _client, _pool
    cfg = get_queue_settings()
    _pool = aioredis.ConnectionPool(
        host=cfg["host"],
        port=cfg["port"],
        db=cfg["db"],
        max_connections=cfg["pool_size"],
    )
    _client = aioredis.Redis(connection_pool=_pool)


def _ensure_pool() -> None:
    if _client is None:
        with _lock:
            if _client is None:
                _init_pool()


async def acquire_client() -> "aioredis.Redis":
    _ensure_pool()
    return _client


async def release_client(client: "aioredis.Redis") -> None:
    """No-op: redis.asyncio releases connections back to the pool automatically."""


async def is_healthy() -> bool:
    try:
        client = await acquire_client()
        await client.ping()
        return True
    except Exception as exc:
        _log.debug("Redis health check failed: %s", exc)
        return False


def stats() -> dict:
    if _pool is None:
        return {"initialized": False}
    return {
        "initialized": True,
        "max_connections": _pool.max_connections,
    }


async def invalidate() -> None:
    global _client, _pool
    with _lock:
        old_pool = _pool
        _client = None
        _pool = None
    if old_pool is not None:
        try:
            await old_pool.disconnect()
        except Exception:
            pass
