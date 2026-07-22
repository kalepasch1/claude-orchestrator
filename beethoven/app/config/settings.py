import os


def get_queue_settings() -> dict:
    return {
        "host": os.environ.get("ORCH_REDIS_HOST", "localhost"),
        "port": int(os.environ.get("ORCH_REDIS_PORT", "6379")),
        "db": int(os.environ.get("ORCH_REDIS_DB", "0")),
        "pool_size": int(os.environ.get("ORCH_QUEUE_POOL_SIZE", "10")),
    }
