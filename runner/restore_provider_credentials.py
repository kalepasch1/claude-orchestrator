#!/usr/bin/env python3
"""Restore missing provider keys from local rotated env backups without logging secrets."""
import argparse
import glob
import os
import tempfile


ALLOWED_KEYS = {
    "XAI_API_KEY", "GROK_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
}


def _assignment(path, key):
    try:
        with open(path, encoding="utf-8") as source:
            for raw in source:
                if raw.startswith(key + "=") and raw.partition("=")[2].strip():
                    return raw.rstrip("\r\n")
    except OSError:
        pass
    return ""


def restore(key, env_path=None):
    if key not in ALLOWED_KEYS:
        raise ValueError(f"unsupported provider credential: {key}")
    env_path = env_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if _assignment(env_path, key):
        return {"key": key, "status": "already-active"}
    # Key-rotation tooling has historically used several suffix conventions;
    # consider every sibling beginning with `.env`, never print its filename,
    # and only extract the explicitly allowlisted assignment.
    backups = [path for path in glob.glob(env_path + "*") if path != env_path and os.path.isfile(path)]
    backups.sort(key=os.path.getmtime, reverse=True)
    assignment = next((_assignment(path, key) for path in backups if _assignment(path, key)), "")
    if not assignment:
        return {"key": key, "status": "not-found"}
    try:
        with open(env_path, encoding="utf-8") as source:
            current = source.read()
    except OSError:
        current = ""
    parent = os.path.dirname(env_path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".env.restore-", dir=parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(current)
            if current and not current.endswith("\n"):
                target.write("\n")
            target.write(assignment + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"key": key, "status": "restored"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("key", choices=sorted(ALLOWED_KEYS))
    args = parser.parse_args()
    result = restore(args.key)
    print(f"{result['key']}: {result['status']}")
