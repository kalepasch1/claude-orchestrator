"""Bounded local embedding transport; no provider fallback or partial vectors."""
import json
import math
import os
import time
import urllib.error
import urllib.request

import local_model_slots as slots


def embed(texts, model, base, timeout=90):
    """Embed at most eight inputs sequentially under the common admission guard.

    A singleton HTTP request avoids multiplying the context allocation by batch
    size. UTF-8 byte bounds conservatively bound tokens; truncate=False also
    rejects model-specific context limits instead of dropping source evidence.
    """
    policy = slots.request_policy()
    if os.environ.get("ORCH_DISABLE_LOCAL_MODELS", "").strip().lower() in ("1", "true", "yes", "on"):
        raise slots.LocalCapacityError("local_disabled")
    if not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= 8:
        raise slots.LocalCapacityError("embedding_batch_budget")
    for text in texts:
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) + 64 > policy["num_ctx"]:
            raise slots.LocalCapacityError("context_budget")
    try:
        deadline_s = float(timeout)
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            deadline_s = policy["timeout_s"]
    except (TypeError, ValueError):
        deadline_s = policy["timeout_s"]
    deadline = time.monotonic() + min(deadline_s, policy["timeout_s"])
    vectors = []
    for text in texts:
        with slots.slot(model, operation="local_embedding") as admission:
            if not isinstance(admission, dict) or admission.get("admitted") is not True or admission.get("locked") is not True:
                raise slots.LocalCapacityError("guard_unavailable")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise slots.LocalCapacityError("request_timeout")
            body = {"model": model, "input": [text], "truncate": False,
                    "keep_alive": policy["keep_alive"], "options": {"num_ctx": policy["num_ctx"]}}
            request = urllib.request.Request(base.rstrip("/") + "/api/embed",
                       data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise slots.LocalCapacityError("embedding_response_invalid")
                data = json.loads(raw)
            except slots.LocalCapacityError:
                raise
            except urllib.error.HTTPError as error:
                raise slots.LocalCapacityError("local_queue_full" if error.code == 503 else "local_request_failed") from None
            except (TimeoutError, urllib.error.URLError, OSError):
                raise slots.LocalCapacityError("local_request_failed") from None
            except (ValueError, TypeError):
                raise slots.LocalCapacityError("embedding_response_invalid") from None
            rows = data.get("embeddings") if isinstance(data, dict) else None
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], list) or not rows[0]:
                raise slots.LocalCapacityError("embedding_response_invalid")
            vector = rows[0]
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in vector):
                raise slots.LocalCapacityError("embedding_response_invalid")
            vectors.append(vector)
    return vectors
