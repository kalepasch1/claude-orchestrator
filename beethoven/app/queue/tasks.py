import json

from beethoven.app.queue import queue_backend


async def enqueue_task(task_data: dict) -> bool:
    """Push task_data into the Redis queue. Returns True on success."""
    client = await queue_backend.acquire_client()
    try:
        await client.rpush("task_queue", json.dumps(task_data))
        return True
    except Exception:
        return False
    finally:
        await queue_backend.release_client(client)
